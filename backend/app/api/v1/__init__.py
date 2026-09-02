"""API version 1 routers.

The version lives in the URL path (api.md section 1.1). Header-based versioning
is cleaner in theory but harder to exercise from a browser or curl, and path
versioning makes it obvious in every access log which contract was used.
"""

from fastapi import APIRouter

from app.api.v1 import auth, health

api_router = APIRouter()

# Health is registered without a prefix so it sits at /api/v1/health.
api_router.include_router(health.router)
api_router.include_router(auth.router)

__all__ = ["api_router"]
