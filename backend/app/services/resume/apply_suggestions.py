"""Turn accepted suggestions into a new resume version (US-6.1 AC3).

## The source version is never touched

Accepting produces a **new** `resume_versions` row. The original keeps its file,
its extracted text and its parse output exactly as they were, which is what makes
"undo" mean putting the old version back rather than hoping an edit was
reversible.

## The new version is a text document, and says so

We cannot rewrite the user's PDF -- reflowing a designed document around edited
sentences is a different and much larger problem, and a bad attempt produces a
file they would be embarrassed to send. So the new version is plain text: the
tailored wording, ready to paste into whatever they actually build the document
in.

Stored as a real object with `text/plain` rather than pointing at the original
file. A version whose stored file does not match its own text would hand someone
the untailored PDF while the screen showed the tailored words.

## Replacement is word-exact, whitespace-tolerant

Each accepted suggestion replaces its `original` once. Whitespace is flexible
because extracted PDF text wraps mid-sentence -- `"efficiently
        deployed
on Vercel"` is the same sentence the model writes back on one line -- and a
literal comparison would reject every one of them.

**Words are not flexible.** This is not fuzzy matching: "close enough" would mean
editing a sentence the user never chose to change. A suggestion that cannot be
anchored is skipped and reported, never approximated.

By the time a suggestion reaches here it has already been anchored once, when
the analysis stored it. This is the second check rather than the first, because
the resume could in principle change in between.
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ids import uuid7
from app.integrations.storage import ObjectStorage
from app.models.enums import ProcessingStatus, SuggestionDecision
from app.models.optimization import OptimizationAnalysis, OptimizationSuggestion
from app.models.resume import ResumeVersion
from app.services.resume.anchoring import replace_span


@dataclass(frozen=True, slots=True)
class ApplyResult:
    version: ResumeVersion
    applied: int
    rejected: int
    #: Accepted suggestions whose original text was not found.
    not_found: int


class NothingToApplyError(ValueError):
    """No accepted suggestion could be applied, so no version was created.

    A version identical to its parent is not a new draft, it is clutter with a
    number on it -- and it would imply a change the user could not find.
    """


async def apply_accepted(
    session: AsyncSession,
    *,
    analysis: OptimizationAnalysis,
    source: ResumeVersion,
    accepted_ids: set[uuid.UUID],
    storage: ObjectStorage,
) -> ApplyResult:
    """Create a new version from the accepted suggestions.

    Every suggestion in the analysis is decided here, not only the accepted
    ones: leaving the rest PENDING would re-offer text the user has already
    passed over.
    """
    rows = list(
        await session.scalars(
            select(OptimizationSuggestion)
            .where(OptimizationSuggestion.analysis_id == analysis.id)
            .order_by(OptimizationSuggestion.position)
        )
    )

    # Decided in full before anything is written.
    #
    # The first version wrote each decision as it went and raised at the end if
    # nothing had applied, leaving the caller to roll the session back. That
    # works, but it makes correctness depend on the caller remembering to undo —
    # and "the write already happened, please ignore it" is a worse contract
    # than never having written. Nothing below the raise touches a row.
    text = source.raw_text or ""
    applied: list[OptimizationSuggestion] = []
    not_found: list[OptimizationSuggestion] = []
    rejected: list[OptimizationSuggestion] = []

    for row in rows:
        if row.id not in accepted_ids:
            rejected.append(row)
            continue

        # Whitespace-tolerant, word-exact. Extracted PDF text wraps mid-sentence,
        # so a literal `in` check fails on lines that are plainly the same --
        # which made every suggestion unappliable the first time this ran for
        # real. It is still not fuzzy: every word must be present, in order.
        updated = replace_span(text, row.original, row.suggested)
        if updated is None:
            not_found.append(row)
        else:
            text = updated
            applied.append(row)

    if not applied:
        raise NothingToApplyError(
            "None of the accepted suggestions could be applied to this resume."
        )

    now = datetime.now(UTC)
    body = text.encode("utf-8")
    next_number = (
        await session.scalar(
            select(func.coalesce(func.max(ResumeVersion.version_number), 0) + 1).where(
                ResumeVersion.resume_id == source.resume_id
            )
        )
    ) or 1

    stem = source.original_filename.rsplit(".", 1)[0]
    key = f"resumes/{source.resume_id}/{uuid7()}.txt"
    await storage.put(key, body, content_type="text/plain")

    version = ResumeVersion(
        id=uuid7(),
        resume_id=source.resume_id,
        version_number=next_number,
        storage_key=key,
        original_filename=f"{stem}-tailored.txt",
        mime_type="text/plain",
        file_size_bytes=len(body),
        content_hash=hashlib.sha256(body).hexdigest(),
        raw_text=text,
        # COMPLETE rather than PENDING: the text is already extracted -- it was
        # built from text. Queueing the parse pipeline would re-derive a profile
        # from wording the user has only proposed, which is not the same as
        # claiming it.
        processing_status=ProcessingStatus.COMPLETE,
        processed_at=now,
    )
    session.add(version)
    await session.flush()

    # Decisions written only now, past every point that could fail.
    for row in rejected:
        row.decision = SuggestionDecision.REJECTED
        row.decided_at = now
    for row in not_found:
        # Accepted, though it could not be placed. The user chose it, and
        # recording a rejection would misrepresent what they decided.
        row.decision = SuggestionDecision.ACCEPTED
        row.decided_at = now
    for row in applied:
        row.decision = SuggestionDecision.ACCEPTED
        row.decided_at = now
        row.applied_version_id = version.id

    return ApplyResult(
        version=version,
        applied=len(applied),
        rejected=len(rejected),
        not_found=len(not_found),
    )
