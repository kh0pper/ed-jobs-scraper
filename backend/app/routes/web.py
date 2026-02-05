"""Web routes for HTML pages."""

from uuid import UUID
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Request, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.base import get_db
from app.models.organization import Organization
from app.models.job_posting import JobPosting
from app.models.scrape_source import ScrapeSource
from app.services.category_normalizer import get_all_categories

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@router.get("/", response_class=HTMLResponse)
async def home(request: Request, db: AsyncSession = Depends(get_db)):
    """Home page with stats and recent jobs."""
    # Get job stats
    total_jobs = (await db.execute(
        select(func.count(JobPosting.id)).where(JobPosting.is_active == True)
    )).scalar() or 0

    active_jobs = total_jobs

    # Jobs by platform
    platform_query = (
        select(JobPosting.platform, func.count(JobPosting.id).label("count"))
        .where(JobPosting.is_active == True)
        .group_by(JobPosting.platform)
        .order_by(func.count(JobPosting.id).desc())
    )
    platform_result = await db.execute(platform_query)
    by_platform = {row.platform: row.count for row in platform_result}

    # Jobs by category (top 15)
    category_query = (
        select(JobPosting.category, func.count(JobPosting.id).label("count"))
        .where(JobPosting.is_active == True)
        .where(JobPosting.category.isnot(None))
        .group_by(JobPosting.category)
        .order_by(func.count(JobPosting.id).desc())
        .limit(15)
    )
    category_result = await db.execute(category_query)
    by_category = {row.category: row.count for row in category_result}

    # Jobs by city (top 10)
    city_query = (
        select(JobPosting.city, func.count(JobPosting.id).label("count"))
        .where(JobPosting.is_active == True)
        .where(JobPosting.city.isnot(None))
        .group_by(JobPosting.city)
        .order_by(func.count(JobPosting.id).desc())
        .limit(10)
    )
    city_result = await db.execute(city_query)
    by_city = {row.city: row.count for row in city_result}

    # Total orgs and sources
    total_orgs = (await db.execute(select(func.count(Organization.id)))).scalar() or 0
    total_sources = (await db.execute(
        select(func.count(ScrapeSource.id)).where(ScrapeSource.is_active == True)
    )).scalar() or 0

    # Recent jobs with org names
    recent_jobs_query = (
        select(JobPosting, Organization.name.label("org_name"))
        .outerjoin(Organization, JobPosting.organization_id == Organization.id)
        .where(JobPosting.is_active == True)
        .order_by(JobPosting.first_seen_at.desc())
        .limit(10)
    )
    recent_result = await db.execute(recent_jobs_query)
    recent_jobs = [
        {
            "id": row.JobPosting.id,
            "title": row.JobPosting.title,
            "org_name": row.org_name,
            "category": row.JobPosting.category,
            "city": row.JobPosting.city,
        }
        for row in recent_result
    ]

    stats = {
        "total_jobs": total_jobs,
        "active_jobs": active_jobs,
        "total_orgs": total_orgs,
        "total_sources": total_sources,
        "by_platform": by_platform,
        "by_category": by_category,
        "by_city": by_city,
    }

    return templates.TemplateResponse(
        "index.html",
        {"request": request, "stats": stats, "recent_jobs": recent_jobs},
    )


@router.get("/jobs", response_class=HTMLResponse)
async def jobs_list(
    request: Request,
    db: AsyncSession = Depends(get_db),
    search: str | None = None,
    category: str | None = None,
    city: str | None = None,
    platform: str | None = None,
    page: int = 1,
):
    """Jobs listing page with filters."""
    limit = 20
    skip = (page - 1) * limit

    # Build query
    query = (
        select(JobPosting, Organization.name.label("org_name"))
        .outerjoin(Organization, JobPosting.organization_id == Organization.id)
        .where(JobPosting.is_active == True)
    )
    count_query = select(func.count(JobPosting.id)).where(JobPosting.is_active == True)

    if search:
        query = query.where(JobPosting.title.ilike(f"%{search}%"))
        count_query = count_query.where(JobPosting.title.ilike(f"%{search}%"))
    if category:
        query = query.where(JobPosting.category == category)
        count_query = count_query.where(JobPosting.category == category)
    if city:
        query = query.where(JobPosting.city.ilike(f"%{city}%"))
        count_query = count_query.where(JobPosting.city.ilike(f"%{city}%"))
    if platform:
        query = query.where(JobPosting.platform == platform)
        count_query = count_query.where(JobPosting.platform == platform)

    query = query.order_by(JobPosting.first_seen_at.desc()).offset(skip).limit(limit)

    result = await db.execute(query)
    jobs = [
        {
            "id": row.JobPosting.id,
            "title": row.JobPosting.title,
            "application_url": row.JobPosting.application_url,
            "org_name": row.org_name,
            "category": row.JobPosting.category,
            "city": row.JobPosting.city,
            "platform": row.JobPosting.platform,
            "posting_date": row.JobPosting.posting_date,
        }
        for row in result
    ]

    total = (await db.execute(count_query)).scalar() or 0

    # Get filter options
    categories = get_all_categories()
    platform_query = select(JobPosting.platform).distinct()
    platform_result = await db.execute(platform_query)
    platforms = sorted([row[0] for row in platform_result if row[0]])

    # Build pagination query string
    params = {}
    if search:
        params["search"] = search
    if category:
        params["category"] = category
    if city:
        params["city"] = city
    if platform:
        params["platform"] = platform
    pagination_query = urlencode(params)

    filters = {
        "search": search,
        "category": category,
        "city": city,
        "platform": platform,
    }

    return templates.TemplateResponse(
        "jobs/list.html",
        {
            "request": request,
            "jobs": jobs,
            "total": total,
            "page": page,
            "limit": limit,
            "filters": filters,
            "categories": categories,
            "platforms": platforms,
            "pagination_query": pagination_query,
        },
    )


@router.get("/jobs/map", response_class=HTMLResponse)
async def jobs_map(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Map view of job postings with Leaflet.js."""
    # Get count of geocoded jobs for display
    geocoded_count = (await db.execute(
        select(func.count(JobPosting.id))
        .where(JobPosting.is_active == True)
        .where(JobPosting.latitude.isnot(None))
        .where(JobPosting.longitude.isnot(None))
    )).scalar() or 0

    # Get some stats for the map sidebar
    city_query = (
        select(JobPosting.city, func.count(JobPosting.id).label("count"))
        .where(JobPosting.is_active == True)
        .where(JobPosting.city.isnot(None))
        .group_by(JobPosting.city)
        .order_by(func.count(JobPosting.id).desc())
        .limit(10)
    )
    city_result = await db.execute(city_query)
    top_cities = [(row.city, row.count) for row in city_result]

    return templates.TemplateResponse(
        "jobs/map.html",
        {
            "request": request,
            "geocoded_count": geocoded_count,
            "top_cities": top_cities,
        },
    )


@router.get("/jobs/{job_id}", response_class=HTMLResponse)
async def job_detail(request: Request, job_id: UUID, db: AsyncSession = Depends(get_db)):
    """Single job detail page."""
    query = (
        select(JobPosting)
        .options(selectinload(JobPosting.organization))
        .where(JobPosting.id == job_id)
    )
    result = await db.execute(query)
    job = result.scalar_one_or_none()

    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    return templates.TemplateResponse(
        "jobs/detail.html",
        {"request": request, "job": job, "organization": job.organization},
    )


@router.get("/orgs", response_class=HTMLResponse)
async def orgs_list(
    request: Request,
    db: AsyncSession = Depends(get_db),
    search: str | None = None,
    org_type: str | None = None,
    esc_region: int | None = None,
    platform_status: str | None = None,
    page: int = 1,
):
    """Organizations listing page with filters."""
    limit = 24
    skip = (page - 1) * limit

    # Build query
    query = select(Organization)
    count_query = select(func.count(Organization.id))

    if search:
        query = query.where(Organization.name.ilike(f"%{search}%"))
        count_query = count_query.where(Organization.name.ilike(f"%{search}%"))
    if org_type:
        query = query.where(Organization.org_type == org_type)
        count_query = count_query.where(Organization.org_type == org_type)
    if esc_region:
        query = query.where(Organization.esc_region == esc_region)
        count_query = count_query.where(Organization.esc_region == esc_region)
    if platform_status:
        query = query.where(Organization.platform_status == platform_status)
        count_query = count_query.where(Organization.platform_status == platform_status)

    query = query.order_by(Organization.name).offset(skip).limit(limit)
    result = await db.execute(query)
    orgs = result.scalars().all()

    # Get job counts for these orgs
    org_ids = [org.id for org in orgs]
    if org_ids:
        job_counts_query = (
            select(JobPosting.organization_id, func.count(JobPosting.id).label("count"))
            .where(JobPosting.organization_id.in_(org_ids))
            .where(JobPosting.is_active == True)
            .group_by(JobPosting.organization_id)
        )
        job_result = await db.execute(job_counts_query)
        job_counts = {row.organization_id: row.count for row in job_result}
    else:
        job_counts = {}

    # Add job counts to orgs
    organizations = []
    for org in orgs:
        org_dict = {
            "id": org.id,
            "name": org.name,
            "org_type": org.org_type,
            "city": org.city,
            "esc_region": org.esc_region,
            "active_job_count": job_counts.get(org.id, 0),
        }
        organizations.append(org_dict)

    total = (await db.execute(count_query)).scalar() or 0

    # Build pagination query string
    params = {}
    if search:
        params["search"] = search
    if org_type:
        params["org_type"] = org_type
    if esc_region:
        params["esc_region"] = str(esc_region)
    if platform_status:
        params["platform_status"] = platform_status
    pagination_query = urlencode(params)

    filters = {
        "search": search,
        "org_type": org_type,
        "esc_region": esc_region,
        "platform_status": platform_status,
    }

    return templates.TemplateResponse(
        "orgs/list.html",
        {
            "request": request,
            "organizations": organizations,
            "total": total,
            "page": page,
            "limit": limit,
            "filters": filters,
            "pagination_query": pagination_query,
        },
    )


@router.get("/orgs/{org_id}", response_class=HTMLResponse)
async def org_detail(request: Request, org_id: UUID, db: AsyncSession = Depends(get_db)):
    """Single organization detail page."""
    # Get organization with counts
    org_query = select(Organization).where(Organization.id == org_id)
    org_result = await db.execute(org_query)
    org = org_result.scalar_one_or_none()

    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")

    # Get source and job counts
    source_count = (await db.execute(
        select(func.count(ScrapeSource.id))
        .where(ScrapeSource.organization_id == org_id)
        .where(ScrapeSource.is_active == True)
    )).scalar() or 0

    job_count = (await db.execute(
        select(func.count(JobPosting.id))
        .where(JobPosting.organization_id == org_id)
        .where(JobPosting.is_active == True)
    )).scalar() or 0

    # Get scrape sources
    sources_query = (
        select(ScrapeSource)
        .where(ScrapeSource.organization_id == org_id)
        .order_by(ScrapeSource.platform)
    )
    sources_result = await db.execute(sources_query)
    sources = sources_result.scalars().all()

    # Get jobs (limit to 50 for display)
    jobs_query = (
        select(JobPosting)
        .where(JobPosting.organization_id == org_id)
        .where(JobPosting.is_active == True)
        .order_by(JobPosting.first_seen_at.desc())
        .limit(50)
    )
    jobs_result = await db.execute(jobs_query)
    jobs = jobs_result.scalars().all()

    # Build org with stats
    org_data = {
        "id": org.id,
        "name": org.name,
        "org_type": org.org_type,
        "tea_id": org.tea_id,
        "city": org.city,
        "state": org.state,
        "county": org.county,
        "esc_region": org.esc_region,
        "total_students": org.total_students,
        "district_type": org.district_type,
        "charter_status": org.charter_status,
        "website_url": org.website_url,
        "platform_status": org.platform_status,
        "source_count": source_count,
        "active_job_count": job_count,
    }

    return templates.TemplateResponse(
        "orgs/detail.html",
        {
            "request": request,
            "org": org_data,
            "sources": sources,
            "jobs": jobs,
            "job_count": job_count,
        },
    )
