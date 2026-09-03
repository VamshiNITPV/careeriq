"""Profile endpoints (api.md section 2.2).

NOTE: this router must never declare a path parameter directly under /profile.
`/profile/skills` is served by a separate router (api/v1/skills.py), and a
`GET /profile/{something}` here would shadow it.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.api.deps import CurrentUser, ProfileServiceDep
from app.schemas.common import ErrorResponse
from app.schemas.profile import (
    PreferencesRead,
    PreferencesReplace,
    ProfilePersonalUpdate,
    ProfileRead,
)

router = APIRouter(prefix="/profile", tags=["profile"])

_AUTH_ERRORS: dict[int | str, dict[str, object]] = {
    401: {"model": ErrorResponse, "description": "Not signed in"},
}


@router.get("", response_model=ProfileRead, summary="Your profile", responses=_AUTH_ERRORS)
async def get_profile(user: CurrentUser, service: ProfileServiceDep) -> ProfileRead:
    # `ensure` rather than a plain get: accounts created outside local
    # registration have no profile row, and a 404 for your own profile would be
    # a confusing way to say "nothing here yet".
    return ProfileRead.model_validate(await service.ensure(user.id))


@router.patch(
    "",
    response_model=ProfileRead,
    summary="Update personal details",
    responses={**_AUTH_ERRORS, 422: {"model": ErrorResponse, "description": "Invalid field"}},
)
async def update_profile(
    payload: ProfilePersonalUpdate, user: CurrentUser, service: ProfileServiceDep
) -> ProfileRead:
    """Partial update — only the fields present in the body are changed.

    `exclude_unset=True` is what makes that true. Without it every optional
    field arrives as None and editing one field silently clears the rest.

    Returns the full profile so the client can update its cached copy from the
    response, rather than firing a second request to read back what it just
    wrote.
    """
    changes = payload.model_dump(exclude_unset=True)
    profile = await service.update_personal(user_id=user.id, changes=changes)
    return ProfileRead.model_validate(profile)


@router.get(
    "/preferences",
    response_model=PreferencesRead,
    summary="Career preferences",
    responses=_AUTH_ERRORS,
)
async def get_preferences(user: CurrentUser, service: ProfileServiceDep) -> PreferencesRead:
    return PreferencesRead.model_validate(await service.ensure(user.id))


@router.put(
    "/preferences",
    response_model=PreferencesRead,
    summary="Replace career preferences",
    responses={**_AUTH_ERRORS, 422: {"model": ErrorResponse, "description": "Invalid preferences"}},
)
async def replace_preferences(
    payload: PreferencesReplace, user: CurrentUser, service: ProfileServiceDep
) -> PreferencesRead:
    """PUT, not PATCH — the whole preference set is replaced.

    These are list fields, and with PATCH "clear this list" and "leave this list
    alone" are the same payload. Replace-wholesale has one meaning, and matches
    how a settings form submits.

    Saving genuinely different values bumps `preferences_updated_at`, which is
    the recommendation cache key (US-1.4 AC2). A no-op save does not.
    """
    profile = await service.replace_preferences(user_id=user.id, preferences=payload)
    return PreferencesRead.model_validate(profile)
