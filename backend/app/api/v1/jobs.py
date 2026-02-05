"""Job posting API endpoints."""

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.base import get_db
from app.models.job_posting import JobPosting
from app.models.organization import Organization

# Valid organization types
OrgType = Literal["isd", "charter", "esc", "nonprofit", "state_agency", "association", "for_profit", "higher_ed"]
from app.schemas.job_posting import (
    JobPostingRead,
    JobPostingSummary,
    JobPostingWithOrg,
    JobStats,
)
from app.schemas.organization import OrganizationSummary

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.get("", response_model=list[JobPostingSummary])
async def list_jobs(
    db: AsyncSession = Depends(get_db),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    search: str | None = Query(None, min_length=2, description="Search in title"),
    city: str | None = Query(None, description="Filter by city"),
    state: str | None = Query(None, max_length=2, description="Filter by state (2-letter code)"),
    category: str | None = Query(None, description="Filter by category"),
    platform: str | None = Query(None, description="Filter by platform"),
    organization_id: UUID | None = Query(None, description="Filter by organization"),
    org_type: OrgType | None = Query(None, description="Filter by organization type (isd, charter, nonprofit, etc.)"),
    esc_region: int | None = Query(None, ge=1, le=20, description="Filter by ESC region (1-20)"),
    active_only: bool = Query(True, description="Only return active jobs"),
):
    """List jobs with filters."""
    query = select(JobPosting)

    # Join with Organization if we need org-related filters
    if org_type or esc_region:
        query = query.join(Organization, JobPosting.organization_id == Organization.id)

    if search:
        query = query.where(JobPosting.title.ilike(f"%{search}%"))
    if city:
        query = query.where(JobPosting.city.ilike(f"%{city}%"))
    if state:
        query = query.where(JobPosting.state == state.upper())
    if category:
        query = query.where(JobPosting.category == category)
    if platform:
        query = query.where(JobPosting.platform == platform)
    if organization_id:
        query = query.where(JobPosting.organization_id == organization_id)
    if org_type:
        query = query.where(Organization.org_type == org_type)
    if esc_region:
        query = query.where(Organization.esc_region == esc_region)
    if active_only:
        query = query.where(JobPosting.is_active == True)

    query = query.order_by(JobPosting.posting_date.desc().nullslast()).offset(skip).limit(limit)
    result = await db.execute(query)
    return result.scalars().all()


@router.get("/stats", response_model=JobStats)
async def get_job_stats(
    db: AsyncSession = Depends(get_db),
    active_only: bool = Query(True, description="Only count active jobs"),
):
    """Get aggregate job statistics."""
    base_filter = JobPosting.is_active == True if active_only else True

    # Total jobs
    total_query = select(func.count(JobPosting.id)).where(base_filter)
    total = (await db.execute(total_query)).scalar() or 0

    # Active jobs
    active_query = select(func.count(JobPosting.id)).where(JobPosting.is_active == True)
    active = (await db.execute(active_query)).scalar() or 0

    # By platform
    platform_query = (
        select(JobPosting.platform, func.count(JobPosting.id).label("count"))
        .where(base_filter)
        .group_by(JobPosting.platform)
        .order_by(func.count(JobPosting.id).desc())
    )
    platform_result = await db.execute(platform_query)
    by_platform = {row.platform: row.count for row in platform_result}

    # By category (top 20)
    category_query = (
        select(JobPosting.category, func.count(JobPosting.id).label("count"))
        .where(base_filter)
        .where(JobPosting.category.isnot(None))
        .group_by(JobPosting.category)
        .order_by(func.count(JobPosting.id).desc())
        .limit(20)
    )
    category_result = await db.execute(category_query)
    by_category = {row.category: row.count for row in category_result}

    # By city (top 20)
    city_query = (
        select(JobPosting.city, func.count(JobPosting.id).label("count"))
        .where(base_filter)
        .where(JobPosting.city.isnot(None))
        .group_by(JobPosting.city)
        .order_by(func.count(JobPosting.id).desc())
        .limit(20)
    )
    city_result = await db.execute(city_query)
    by_city = {row.city: row.count for row in city_result}

    return JobStats(
        total_jobs=total,
        active_jobs=active,
        by_platform=by_platform,
        by_category=by_category,
        by_city=by_city,
    )


@router.get("/{job_id}", response_model=JobPostingWithOrg)
async def get_job(
    job_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """Get a single job by ID with organization info."""
    query = (
        select(JobPosting)
        .options(selectinload(JobPosting.organization))
        .where(JobPosting.id == job_id)
    )
    result = await db.execute(query)
    job = result.scalar_one_or_none()

    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    # Build response with organization
    job_data = JobPostingRead.model_validate(job).model_dump()
    org_data = OrganizationSummary.model_validate(job.organization) if job.organization else None

    return JobPostingWithOrg(**job_data, organization=org_data)
