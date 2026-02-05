"""Organization API endpoints."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.base import get_db
from app.models.organization import Organization
from app.models.scrape_source import ScrapeSource
from app.models.job_posting import JobPosting
from app.schemas.organization import (
    OrganizationRead,
    OrganizationWithStats,
)
from app.schemas.job_posting import JobPostingSummary
from app.schemas.scrape_source import ScrapeSourceSummary

router = APIRouter(prefix="/organizations", tags=["organizations"])


@router.get("", response_model=list[OrganizationWithStats])
async def list_organizations(
    db: AsyncSession = Depends(get_db),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    org_type: str | None = Query(None, description="Filter by org type (isd, charter, etc.)"),
    esc_region: int | None = Query(None, ge=1, le=20, description="Filter by ESC region (1-20)"),
    county: str | None = Query(None, description="Filter by county"),
    platform_status: str | None = Query(None, description="Filter by platform status"),
    search: str | None = Query(None, min_length=2, description="Search by name"),
):
    """List organizations with optional filters."""
    query = select(Organization)

    if org_type:
        query = query.where(Organization.org_type == org_type)
    if esc_region:
        query = query.where(Organization.esc_region == esc_region)
    if county:
        query = query.where(Organization.county.ilike(f"%{county}%"))
    if platform_status:
        query = query.where(Organization.platform_status == platform_status)
    if search:
        query = query.where(Organization.name.ilike(f"%{search}%"))

    query = query.order_by(Organization.name).offset(skip).limit(limit)
    result = await db.execute(query)
    orgs = result.scalars().all()

    # Get counts for each org
    org_ids = [org.id for org in orgs]
    if org_ids:
        # Source counts
        source_counts_query = (
            select(ScrapeSource.organization_id, func.count(ScrapeSource.id).label("count"))
            .where(ScrapeSource.organization_id.in_(org_ids))
            .where(ScrapeSource.is_active == True)
            .group_by(ScrapeSource.organization_id)
        )
        source_result = await db.execute(source_counts_query)
        source_counts = {row.organization_id: row.count for row in source_result}

        # Job counts
        job_counts_query = (
            select(JobPosting.organization_id, func.count(JobPosting.id).label("count"))
            .where(JobPosting.organization_id.in_(org_ids))
            .where(JobPosting.is_active == True)
            .group_by(JobPosting.organization_id)
        )
        job_result = await db.execute(job_counts_query)
        job_counts = {row.organization_id: row.count for row in job_result}
    else:
        source_counts = {}
        job_counts = {}

    return [
        OrganizationWithStats(
            **OrganizationRead.model_validate(org).model_dump(),
            source_count=source_counts.get(org.id, 0),
            active_job_count=job_counts.get(org.id, 0),
        )
        for org in orgs
    ]


@router.get("/{org_id}", response_model=OrganizationWithStats)
async def get_organization(
    org_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """Get a single organization by ID."""
    query = select(Organization).where(Organization.id == org_id)
    result = await db.execute(query)
    org = result.scalar_one_or_none()

    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")

    # Get counts
    source_count_query = (
        select(func.count(ScrapeSource.id))
        .where(ScrapeSource.organization_id == org_id)
        .where(ScrapeSource.is_active == True)
    )
    source_count = (await db.execute(source_count_query)).scalar() or 0

    job_count_query = (
        select(func.count(JobPosting.id))
        .where(JobPosting.organization_id == org_id)
        .where(JobPosting.is_active == True)
    )
    job_count = (await db.execute(job_count_query)).scalar() or 0

    return OrganizationWithStats(
        **OrganizationRead.model_validate(org).model_dump(),
        source_count=source_count,
        active_job_count=job_count,
    )


@router.get("/{org_id}/sources", response_model=list[ScrapeSourceSummary])
async def get_organization_sources(
    org_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """Get scrape sources for an organization."""
    # Verify org exists
    org_query = select(Organization.id).where(Organization.id == org_id)
    org_result = await db.execute(org_query)
    if not org_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Organization not found")

    query = (
        select(ScrapeSource)
        .where(ScrapeSource.organization_id == org_id)
        .order_by(ScrapeSource.platform)
    )
    result = await db.execute(query)
    return result.scalars().all()


@router.get("/{org_id}/jobs", response_model=list[JobPostingSummary])
async def get_organization_jobs(
    org_id: UUID,
    db: AsyncSession = Depends(get_db),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    active_only: bool = Query(True, description="Only return active jobs"),
):
    """Get jobs for an organization."""
    # Verify org exists
    org_query = select(Organization.id).where(Organization.id == org_id)
    org_result = await db.execute(org_query)
    if not org_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Organization not found")

    query = select(JobPosting).where(JobPosting.organization_id == org_id)

    if active_only:
        query = query.where(JobPosting.is_active == True)

    query = query.order_by(JobPosting.posting_date.desc().nullslast()).offset(skip).limit(limit)
    result = await db.execute(query)
    return result.scalars().all()
