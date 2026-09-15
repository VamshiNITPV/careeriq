"""Turn accepted suggestions into a new resume version (US-6.1 AC3).

## The source version is never touched

Accepting produces a **new** `resume_versions` row. The original keeps its file,
its extracted text and its parse output exactly as they were, which is what makes
"undo" mean putting the old version back rather than hoping an edit was
reversible.

## The new version is a generated document, not a copy of theirs

The tailored wording is rendered as a **new PDF** (`services/resume/pdf.py`).
Deliberately a clean single-column document rather than a reproduction of the
uploaded design: their original has fonts, columns and spacing we only ever saw
as extracted text, and re-typesetting a layout from its own output produces
something subtly wrong.

It gets its own stored object rather than pointing at the original file. A
version whose stored file does not match its own text would hand someone the
untailored document while the screen showed the tailored words.

`raw_text` carries the exact tailored text and is the version's text of record
-- it is what the `.txt` download and the on-page preview are built from, so
both formats are the same words by construction rather than by coincidence.

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
from app.core.logging import get_logger
from app.integrations.storage import ObjectStorage, build_storage_key
from app.models.enums import ProcessingStatus, SuggestionDecision
from app.models.optimization import OptimizationAnalysis, OptimizationSuggestion
from app.models.resume import ResumeVersion
from app.services.resume.anchoring import replace_span
from app.services.resume.pdf import build_resume_pdf
from app.services.resume.pdf_edit import NotEditableError, edit_pdf_in_place

log = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class ApplyResult:
    version: ResumeVersion
    applied: int
    rejected: int
    #: Accepted suggestions whose original text was not found.
    not_found: int
    #: True when the new file is the user's own document with the sentences
    #: swapped in, rather than a fresh rendering of the text.
    #:
    #: Reported because the two are visibly different things to receive, and
    #: which one arrived is not something the reader should have to work out by
    #: opening it.
    kept_layout: bool = False


#: Matches the `file_size_within_limit` CHECK on resume_versions.
_MAX_FILE_BYTES = 5 * 1024 * 1024


class DocumentTooLargeError(ValueError):
    """The rendered PDF exceeds what a resume version may hold."""


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
    stem = source.original_filename.rsplit(".", 1)[0]

    # Preferred: edit the document they designed, so what comes back still looks
    # like their resume. Falls back to a clean rendering when the source is not
    # a PDF, or when the edits cannot be placed without damaging the layout --
    # `edit_pdf_in_place` refuses rather than half-applying, and a plain
    # document is a better answer than a broken one.
    body, kept_layout = await _render(storage, source, text, stem, applied)

    # The column has a CHECK for this. Without the guard it surfaces as an
    # IntegrityError at flush -- a database error for what is a plain domain
    # fact about the document being too large.
    if len(body) > _MAX_FILE_BYTES:
        raise DocumentTooLargeError(
            "The tailored resume came out larger than we can store."
        )

    next_number = (
        await session.scalar(
            select(func.coalesce(func.max(ResumeVersion.version_number), 0) + 1).where(
                ResumeVersion.resume_id == source.resume_id
            )
        )
    ) or 1

    # `build_storage_key`, not a hand-rolled path. Uploads partition by user;
    # this used to partition by resume, putting tailored files in a sibling
    # namespace that a per-user prefix delete would walk straight past.
    key = build_storage_key(user_id=str(analysis.user_id), extension=".pdf")
    await storage.put(key, body, content_type="application/pdf")

    version = ResumeVersion(
        id=uuid7(),
        resume_id=source.resume_id,
        version_number=next_number,
        storage_key=key,
        original_filename=f"{stem}-tailored.pdf",
        mime_type="application/pdf",
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
        kept_layout=kept_layout,
    )


async def _render(
    storage: ObjectStorage,
    source: ResumeVersion,
    text: str,
    stem: str,
    applied: list[OptimizationSuggestion],
) -> tuple[bytes, bool]:
    """The tailored document, and whether it kept the original layout."""
    clean = build_resume_pdf(text, title=f"{stem} (tailored)")

    if source.mime_type != "application/pdf":
        return clean, False

    try:
        original = await storage.get(source.storage_key)
        edited = edit_pdf_in_place(original, [(row.original, row.suggested) for row in applied])
    except NotEditableError as exc:
        log.info("apply: falling back to a generated document", reason=str(exc))
        return clean, False
    except Exception as exc:
        # Never let this path fail the apply. The clean document is always
        # available and always correct; keeping the layout is the bonus.
        log.warning("apply: in-place edit failed", error=f"{type(exc).__name__}: {exc}")
        return clean, False

    if edited.applied != len(applied):
        # Some sentence could not be placed. Shipping a document missing half
        # the accepted changes would misrepresent what the user chose, so the
        # complete rendering wins.
        log.info(
            "apply: layout edit incomplete, using a generated document",
            wanted=len(applied),
            placed=edited.applied,
        )
        return clean, False

    return edited.pdf, True
