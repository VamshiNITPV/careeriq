"""Profile business logic.

Knows nothing about HTTP, like every other service (architecture.md section 2).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from app.core.ids import uuid7
from app.core.logging import get_logger
from app.models.profile import Profile
from app.repositories.user import ProfileRepository
from app.schemas.profile import PreferencesReplace
from app.services.resume.contact import ContactDetails

log = get_logger(__name__)

# Fields the resume parser may fill. Deliberately excludes country_code,
# salary_currency, years_of_experience and current_experience_level: inferring
# those from free text needs reference data this project does not have, and a
# wrong country silently distorts the location dimension of the ranking formula.
AUTOFILLABLE = (
    "full_name",
    "phone",
    "location",
    "linkedin_url",
    "github_url",
    "portfolio_url",
)


class ProfileService:
    def __init__(self, *, profiles: ProfileRepository) -> None:
        self.profiles = profiles

    async def ensure(self, user_id: uuid.UUID) -> Profile:
        """Return the user's profile, creating an empty one if absent.

        A row is normally created during local registration (services/auth.py),
        but not for accounts created any other way — OAuth sign-in, fixtures, or
        anything predating that code. Making every read tolerate a missing row
        is simpler than auditing every creation path forever.

        "Create if missing" is policy, which is why it lives here rather than in
        the repository (repositories/base.py).
        """
        profile = await self.profiles.get_by_user_id(user_id)
        if profile is not None:
            return profile

        profile = Profile(id=uuid7(), user_id=user_id)
        self.profiles.add(profile)
        await self.profiles.flush()
        log.info("profile created on first access", user_id=str(user_id))
        return profile

    async def update_personal(self, *, user_id: uuid.UUID, changes: dict[str, Any]) -> Profile:
        """Apply a partial update.

        `changes` must already have been produced with `exclude_unset=True` by
        the caller, so absent fields are missing from the dict rather than
        present as None. Without that, a one-field edit clears everything else.
        """
        profile = await self.ensure(user_id)
        for field, value in changes.items():
            setattr(profile, field, value)

        await self.profiles.flush()
        # Required, not defensive: the flush expires `updated_at` because
        # PostgreSQL computes it, and serialising an expired attribute in async
        # raises MissingGreenlet. See BaseRepository.refresh.
        await self.profiles.refresh(profile)

        log.info("profile updated", user_id=str(user_id), fields=sorted(changes))
        return profile

    async def replace_preferences(
        self, *, user_id: uuid.UUID, preferences: PreferencesReplace
    ) -> Profile:
        """Replace the preference set wholesale."""
        profile = await self.ensure(user_id)

        before = self._preference_snapshot(profile)
        for field, value in preferences.model_dump().items():
            setattr(profile, field, value)

        # Only bump the timestamp when something actually changed. It is the
        # recommendation cache key (ADR-008), so a no-op save should not
        # invalidate every cached ranking for nothing.
        if self._preference_snapshot(profile) != before:
            profile.preferences_updated_at = datetime.now(UTC)
            log.info("preferences replaced", user_id=str(user_id))

        await self.profiles.flush()
        await self.profiles.refresh(profile)
        return profile

    @staticmethod
    def _preference_snapshot(profile: Profile) -> tuple[Any, ...]:
        return (
            tuple(profile.target_roles or ()),
            tuple(profile.preferred_locations or ()),
            tuple(profile.preferred_work_modes or ()),
            tuple(profile.preferred_employment_types or ()),
            profile.min_salary_expectation,
            profile.salary_currency,
            profile.open_to_relocation,
        )

    async def apply_extracted_contact(
        self, *, user_id: uuid.UUID, contact: ContactDetails
    ) -> dict[str, list[str]]:
        """Fill empty profile fields from a parsed resume header.

        **Fill-if-empty is the whole rule.** A field the user has typed is
        non-empty and is therefore never touched — the requirement is satisfied
        structurally rather than by a flag that has to be checked correctly at
        every write site.

        A per-field provenance flag (like CandidateSkill.is_user_verified) would
        be overkill here, and the difference is instructive: skills need one
        because a re-parse rewrites the same rows repeatedly and can genuinely
        collide with a user's edit. Contact autofill only ever writes into
        holes, so a collision cannot occur.

        Naturally idempotent, which matters because /reparse exists: the second
        run finds every field already populated and changes nothing.

        Returns {"applied": [...], "skipped": [...]} for the audit trail.
        """
        profile = await self.ensure(user_id)

        applied: list[str] = []
        skipped: list[str] = []

        for field in AUTOFILLABLE:
            value = getattr(contact, field, None)
            if not value:
                continue
            if getattr(profile, field):
                # The user's value wins, always.
                skipped.append(field)
                continue
            setattr(profile, field, value)
            applied.append(field)

        if applied:
            await self.profiles.flush()
            log.info("profile autofilled from resume", user_id=str(user_id), fields=applied)

        return {"applied": applied, "skipped": skipped}
