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


@router.get("/compare")
async def compare_organizations(
    db: AsyncSession = Depends(get_db),
    ids: str = Query(..., description="Comma-separated org UUIDs (2-3)"),
):
    """Compare 2-3 organizations: demographics + job counts by category."""
    from app.models.district_demographics import DistrictDemographics

    org_ids = [id.strip() for id in ids.split(",") if id.strip()]
    if len(org_ids) < 2 or len(org_ids) > 3:
        raise HTTPException(status_code=400, detail="Provide 2-3 organization IDs")

    results = []
    for oid in org_ids:
        # Get org info
        org = (await db.execute(
            select(Organization).where(Organization.id == oid)
        )).scalar_one_or_none()
        if not org:
            raise HTTPException(status_code=404, detail=f"Organization {oid} not found")

        # Latest demographics
        demo = (await db.execute(
            select(DistrictDemographics)
            .where(DistrictDemographics.organization_id == oid)
            .order_by(DistrictDemographics.school_year.desc())
            .limit(1)
        )).scalar_one_or_none()

        # Job counts by category
        cat_query = (
            select(JobPosting.category, func.count(JobPosting.id).label("count"))
            .where(JobPosting.organization_id == oid)
            .where(JobPosting.is_active == True)
            .group_by(JobPosting.category)
            .order_by(func.count(JobPosting.id).desc())
        )
        cat_result = await db.execute(cat_query)
        categories = {row.category: row.count for row in cat_result}

        total_jobs = sum(categories.values())

        org_data = {
            "id": str(org.id),
            "name": org.name,
            "org_type": org.org_type,
            "city": org.city,
            "tea_id": org.tea_id,
            "total_students": org.total_students,
            "total_active_jobs": total_jobs,
            "job_categories": categories,
        }

        if demo:
            org_data["demographics"] = {
                "school_year": demo.school_year,
                "total_students": demo.total_students,
                "economically_disadvantaged": demo.economically_disadvantaged,
                "at_risk": demo.at_risk,
                "ell": demo.ell,
                "special_ed": demo.special_ed,
                "gifted_talented": demo.gifted_talented,
                "homeless": demo.homeless,
                "foster_care": demo.foster_care,
            }

        results.append(org_data)

    return results


@router.get("/{org_id}/demographics")
async def get_organization_demographics(
    org_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """Get demographics for an organization (all school years, most recent first)."""
    from app.models.district_demographics import DistrictDemographics

    # Verify org exists
    org_query = select(Organization.id).where(Organization.id == org_id)
    org_result = await db.execute(org_query)
    if not org_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Organization not found")

    query = (
        select(DistrictDemographics)
        .where(DistrictDemographics.organization_id == org_id)
        .order_by(DistrictDemographics.school_year.desc())
    )
    result = await db.execute(query)
    rows = result.scalars().all()

    return [
        {
            "school_year": r.school_year,
            "total_students": r.total_students,
            "economically_disadvantaged": r.economically_disadvantaged,
            "at_risk": r.at_risk,
            "ell": r.ell,
            "special_ed": r.special_ed,
            "gifted_talented": r.gifted_talented,
            "homeless": r.homeless,
            "foster_care": r.foster_care,
            "economically_disadvantaged_count": r.economically_disadvantaged_count,
            "at_risk_count": r.at_risk_count,
            "ell_count": r.ell_count,
            "special_ed_count": r.special_ed_count,
            "gifted_talented_count": r.gifted_talented_count,
            "homeless_count": r.homeless_count,
            "foster_care_count": r.foster_care_count,
            "bilingual_count": r.bilingual_count,
            "esl_count": r.esl_count,
            "dyslexic_count": r.dyslexic_count,
            "military_connected_count": r.military_connected_count,
            "section_504_count": r.section_504_count,
            "title_i_count": r.title_i_count,
            "migrant_count": r.migrant_count,
        }
        for r in rows
    ]


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
