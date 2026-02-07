"""Web routes for HTML pages."""

from uuid import UUID
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Request, HTTPException, Query
from fastapi.responses import HTMLResponse, RedirectResponse
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


def _escape_ilike(value: str) -> str:
    """Escape % and _ characters for use in ILIKE patterns."""
    return value.replace("%", r"\%").replace("_", r"\_")


async def _get_total_sources(db: AsyncSession) -> int:
    """Get total active source count for footer."""
    return (await db.execute(
        select(func.count(ScrapeSource.id)).where(ScrapeSource.is_active == True)
    )).scalar() or 0


async def _get_filter_options(db: AsyncSession) -> tuple[list[str], list[str]]:
    """Return (categories, platforms) for filter dropdowns."""
    categories = get_all_categories()
    platform_result = await db.execute(select(JobPosting.platform).distinct())
    platforms = sorted([row[0] for row in platform_result if row[0]])
    return categories, platforms


@router.get("/", response_class=HTMLResponse)
async def home(request: Request, db: AsyncSession = Depends(get_db)):
    """Unified job explorer — map + list split-screen."""
    total_jobs = (await db.execute(
        select(func.count(JobPosting.id)).where(JobPosting.is_active == True)
    )).scalar() or 0

    total_sources = await _get_total_sources(db)
    categories, platforms = await _get_filter_options(db)

    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "total_jobs": total_jobs,
            "total_sources": total_sources,
            "categories": categories,
            "platforms": platforms,
        },
    )


@router.get("/jobs/partial", response_class=HTMLResponse)
async def jobs_partial(
    request: Request,
    db: AsyncSession = Depends(get_db),
    mode: str = Query("map", description="View mode: map or list"),
    search: str | None = None,
    category: str | None = None,
    city: str | None = None,
    platform: str | None = None,
    north: float | None = None,
    south: float | None = None,
    east: float | None = None,
    west: float | None = None,
    page: int = 1,
):
    """HTMX partial returning job card HTML for the job list panel."""
    limit = 20
    skip = (page - 1) * limit
    has_bbox = all(v is not None for v in (north, south, east, west))

    # Base query for the list
    query = (
        select(
            JobPosting.id,
            JobPosting.title,
            JobPosting.application_url,
            JobPosting.category,
            JobPosting.city,
            JobPosting.platform,
            JobPosting.latitude,
            JobPosting.longitude,
            JobPosting.posting_date,
            Organization.name.label("org_name"),
        )
        .outerjoin(Organization, JobPosting.organization_id == Organization.id)
        .where(JobPosting.is_active == True)
    )
    count_query = select(func.count(JobPosting.id)).where(JobPosting.is_active == True)

    # In map mode with bbox, spatially filter to geocoded jobs in viewport
    if mode == "map" and has_bbox:
        query = query.where(
            JobPosting.latitude.isnot(None),
            JobPosting.longitude.isnot(None),
            JobPosting.latitude.between(south, north),
            JobPosting.longitude.between(west, east),
        )

    # Text filters apply in both modes
    if search:
        escaped = _escape_ilike(search)
        query = query.where(JobPosting.title.ilike(f"%{escaped}%"))
        count_query = count_query.where(JobPosting.title.ilike(f"%{_escape_ilike(search)}%"))
    if category:
        query = query.where(JobPosting.category == category)
        count_query = count_query.where(JobPosting.category == category)
    if city:
        escaped = _escape_ilike(city)
        query = query.where(JobPosting.city.ilike(f"%{escaped}%"))
        count_query = count_query.where(JobPosting.city.ilike(f"%{_escape_ilike(city)}%"))
    if platform:
        query = query.where(JobPosting.platform == platform)
        count_query = count_query.where(JobPosting.platform == platform)

    # Count for the spatial query (what's shown)
    spatial_count_query = query.with_only_columns(func.count())
    shown_total = (await db.execute(spatial_count_query)).scalar() or 0

    # Total active jobs ignoring bbox (for "X of Y total" display)
    total_all = (await db.execute(count_query)).scalar() or 0

    query = query.order_by(JobPosting.first_seen_at.desc()).offset(skip).limit(limit)
    result = await db.execute(query)

    jobs = []
    for row in result.mappings():
        jobs.append({
            "id": row["id"],
            "title": row["title"],
            "application_url": row["application_url"],
            "org_name": row["org_name"],
            "category": row["category"],
            "city": row["city"],
            "platform": row["platform"],
            "latitude": row["latitude"],
            "longitude": row["longitude"],
            "posting_date": row["posting_date"],
        })

    has_more = (skip + limit) < shown_total

    # Build "show more" query params
    params = {"mode": mode, "page": page + 1}
    if search:
        params["search"] = search
    if category:
        params["category"] = category
    if city:
        params["city"] = city
    if platform:
        params["platform"] = platform
    if has_bbox:
        params["north"] = north
        params["south"] = south
        params["east"] = east
        params["west"] = west
    more_url = f"/jobs/partial?{urlencode(params)}"

    response = templates.TemplateResponse(
        "partials/job_list.html",
        {
            "request": request,
            "jobs": jobs,
            "shown_total": shown_total,
            "total_all": total_all,
            "mode": mode,
            "has_more": has_more,
            "more_url": more_url,
            "page": page,
        },
    )

    # HX-Trigger header so Alpine can update the count display
    response.headers["HX-Trigger"] = f'{{"jobsLoaded": {{"shown": {shown_total}, "total": {total_all}}}}}'

    return response


@router.get("/jobs/map", response_class=RedirectResponse)
async def jobs_map_redirect(request: Request):
    """Redirect old map URL to unified view."""
    return RedirectResponse(url="/?mode=map", status_code=301)


@router.get("/jobs", response_class=RedirectResponse)
async def jobs_list_redirect(request: Request):
    """Redirect old jobs list URL to unified view, preserving query params."""
    params = dict(request.query_params)
    params["mode"] = "list"
    return RedirectResponse(url=f"/?{urlencode(params)}", status_code=301)


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

    total_sources = await _get_total_sources(db)

    return templates.TemplateResponse(
        "jobs/detail.html",
        {
            "request": request,
            "job": job,
            "organization": job.organization,
            "total_sources": total_sources,
        },
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
    total_sources = await _get_total_sources(db)

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
            "total_sources": total_sources,
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

    total_sources = await _get_total_sources(db)

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
            "total_sources": total_sources,
        },
    )
