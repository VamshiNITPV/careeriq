"""API version 1 routers.

The version lives in the URL path (api.md section 1.1). Header-based versioning
is cleaner in theory but harder to exercise from a browser or curl, and path
versioning makes it obvious in every access log which contract was used.
"""

from fastapi import APIRouter

from app.api.v1 import auth, health, jobs, profile, resumes, skills

api_router = APIRouter()

# Health is registered without a prefix so it sits at /api/v1/health.
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(resumes.router)
api_router.include_router(jobs.router)
# Bulk import sits under /admin/jobs rather than /jobs, so it cannot be
# swallowed by /jobs/{job_id}.
api_router.include_router(jobs.admin_router)
api_router.include_router(skills.skills_router)
# /profile and /profile/skills are served by two separate routers. This is safe
# only because neither declares a path parameter directly under /profile — a
# `GET /profile/{id}` would swallow /profile/skills.
api_router.include_router(profile.router)
api_router.include_router(skills.profile_skills_router)

__all__ = ["api_router"]
