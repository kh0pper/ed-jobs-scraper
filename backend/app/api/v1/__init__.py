"""API v1 router aggregation."""

from fastapi import APIRouter

from app.api.v1.organizations import router as organizations_router
from app.api.v1.jobs import router as jobs_router
from app.api.v1.sources import router as sources_router
from app.api.v1.runs import router as runs_router
from app.api.v1.geo import router as geo_router

router = APIRouter(prefix="/api/v1")

router.include_router(organizations_router)
router.include_router(jobs_router)
router.include_router(sources_router)
router.include_router(runs_router)
router.include_router(geo_router)
