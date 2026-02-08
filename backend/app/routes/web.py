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
from app.models.user import User
from app.models.saved_job import SavedJob
from app.models.user_interaction import UserInteraction
from app.services.category_normalizer import get_all_categories
from app.dependencies.auth import get_current_user, ensure_csrf_token

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


async def _ctx(request: Request, db: AsyncSession, **extra) -> dict:
    """Build common template context with current_user, total_sources, csrf_token."""
    user = await get_current_user(request, db)
    total_sources = await _get_total_sources(db)
    csrf_token = ensure_csrf_token(request)

    # Load saved job IDs when logged in
    saved_job_ids = set()
    if user:
        result = await db.execute(
            select(SavedJob.job_posting_id).where(SavedJob.user_id == user.id)
        )
        saved_job_ids = {row[0] for row in result}

    return {
        "request": request,
        "current_user": user,
        "total_sources": total_sources,
        "csrf_token": csrf_token,
        "saved_job_ids": saved_job_ids,
        **extra,
    }


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

    categories, platforms = await _get_filter_options(db)

    # Orgs with active jobs for the ISD filter dropdown
    orgs_query = (
        select(Organization.id, Organization.name, Organization.tea_id)
        .where(Organization.platform_status == "mapped")
        .order_by(Organization.name)
    )
    orgs_result = await db.execute(orgs_query)
    organizations = [
        {"id": str(row.id), "name": row.name, "tea_id": row.tea_id}
        for row in orgs_result
    ]

    ctx = await _ctx(request, db,
        total_jobs=total_jobs,
        categories=categories,
        platforms=platforms,
        organizations=organizations,
    )

    return templates.TemplateResponse("index.html", ctx)


@router.get("/jobs/partial", response_class=HTMLResponse)
async def jobs_partial(
    request: Request,
    db: AsyncSession = Depends(get_db),
    mode: str = Query("map", description="View mode: map or list"),
    search: str | None = None,
    category: str | None = None,
    city: str | None = None,
    platform: str | None = None,
    organization_id: str | None = None,
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
    if organization_id:
        query = query.where(JobPosting.organization_id == organization_id)
        count_query = count_query.where(JobPosting.organization_id == organization_id)

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
    if organization_id:
        params["organization_id"] = organization_id
    if has_bbox:
        params["north"] = north
        params["south"] = south
        params["east"] = east
        params["west"] = west
    more_url = f"/jobs/partial?{urlencode(params)}"

    # Get current user + saved job IDs for save buttons
    ctx = await _ctx(request, db,
        jobs=jobs,
        shown_total=shown_total,
        total_all=total_all,
        mode=mode,
        has_more=has_more,
        more_url=more_url,
        page=page,
    )

    response = templates.TemplateResponse("partials/job_list.html", ctx)

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

    ctx = await _ctx(request, db, job=job, organization=job.organization)

    # Record view interaction if logged in
    if ctx["current_user"]:
        interaction = UserInteraction(
            user_id=ctx["current_user"].id,
            job_posting_id=job_id,
            interaction_type="view",
        )
        db.add(interaction)
        # commit happens in get_db cleanup

    # Get thumbs state for this job
    user_thumbs = {}
    if ctx["current_user"]:
        thumbs_result = await db.execute(
            select(UserInteraction.interaction_type)
            .where(
                UserInteraction.user_id == ctx["current_user"].id,
                UserInteraction.job_posting_id == job_id,
                UserInteraction.interaction_type.in_(["thumbs_up", "thumbs_down"]),
            )
            .order_by(UserInteraction.created_at.desc())
            .limit(1)
        )
        row = thumbs_result.scalar_one_or_none()
        if row:
            user_thumbs[job_id] = row
    ctx["user_thumbs"] = user_thumbs

    return templates.TemplateResponse("jobs/detail.html", ctx)


@router.get("/orgs", response_class=HTMLResponse)
async def orgs_list(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Map-centric ISD explorer."""
    total_orgs = (await db.execute(
        select(func.count(Organization.id))
    )).scalar() or 0

    ctx = await _ctx(request, db, total_orgs=total_orgs)

    return templates.TemplateResponse("orgs/list.html", ctx)


@router.get("/orgs/partial", response_class=HTMLResponse)
async def orgs_partial(
    request: Request,
    db: AsyncSession = Depends(get_db),
    search: str | None = None,
    org_type: str | None = None,
    esc_region: int | None = None,
    platform_status: str | None = None,
    page: int = 1,
):
    """HTMX partial returning org card HTML for the org list panel."""
    limit = 20
    skip = (page - 1) * limit

    query = select(Organization)
    count_query = select(func.count(Organization.id))

    if search:
        escaped = _escape_ilike(search)
        query = query.where(Organization.name.ilike(f"%{escaped}%"))
        count_query = count_query.where(Organization.name.ilike(f"%{_escape_ilike(search)}%"))
    if org_type:
        query = query.where(Organization.org_type == org_type)
        count_query = count_query.where(Organization.org_type == org_type)
    if esc_region:
        query = query.where(Organization.esc_region == esc_region)
        count_query = count_query.where(Organization.esc_region == esc_region)
    if platform_status:
        query = query.where(Organization.platform_status == platform_status)
        count_query = count_query.where(Organization.platform_status == platform_status)

    total = (await db.execute(count_query)).scalar() or 0

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

    organizations = []
    for org in orgs:
        organizations.append({
            "id": org.id,
            "name": org.name,
            "org_type": org.org_type,
            "city": org.city,
            "esc_region": org.esc_region,
            "total_students": org.total_students,
            "active_job_count": job_counts.get(org.id, 0),
        })

    has_more = (skip + limit) < total

    # Build "show more" query params
    params = {"page": page + 1}
    if search:
        params["search"] = search
    if org_type:
        params["org_type"] = org_type
    if esc_region:
        params["esc_region"] = str(esc_region)
    if platform_status:
        params["platform_status"] = platform_status
    more_url = f"/orgs/partial?{urlencode(params)}"

    return templates.TemplateResponse(
        "partials/org_list.html",
        {
            "request": request,
            "organizations": organizations,
            "total": total,
            "has_more": has_more,
            "more_url": more_url,
        },
    )


@router.get("/orgs/compare", response_class=HTMLResponse)
async def orgs_compare(
    request: Request,
    db: AsyncSession = Depends(get_db),
    ids: str = Query("", description="Comma-separated org UUIDs"),
):
    """Side-by-side district comparison page."""
    from app.models.district_demographics import DistrictDemographics

    org_ids = [id.strip() for id in ids.split(",") if id.strip()]
    if len(org_ids) < 2 or len(org_ids) > 3:
        raise HTTPException(status_code=400, detail="Provide 2-3 organization IDs")

    orgs_data = []
    all_categories = set()

    for oid in org_ids:
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
        cat_result = await db.execute(
            select(JobPosting.category, func.count(JobPosting.id).label("count"))
            .where(JobPosting.organization_id == oid)
            .where(JobPosting.is_active == True)
            .group_by(JobPosting.category)
            .order_by(func.count(JobPosting.id).desc())
        )
        categories = {row.category: row.count for row in cat_result}
        all_categories.update(categories.keys())

        orgs_data.append({
            "org": org,
            "demographics": demo,
            "categories": categories,
            "total_jobs": sum(categories.values()),
        })

    ctx = await _ctx(request, db,
        orgs_data=orgs_data,
        all_categories=sorted(all_categories),
        ids=ids,
    )

    return templates.TemplateResponse("orgs/compare.html", ctx)


@router.get("/orgs/{org_id}", response_class=HTMLResponse)
async def org_detail(request: Request, org_id: UUID, db: AsyncSession = Depends(get_db)):
    """Single organization detail page."""
    from app.models.district_demographics import DistrictDemographics

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

    # Get demographics (most recent year)
    demographics_query = (
        select(DistrictDemographics)
        .where(DistrictDemographics.organization_id == org_id)
        .order_by(DistrictDemographics.school_year.desc())
    )
    demographics_result = await db.execute(demographics_query)
    demographics = demographics_result.scalars().all()

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

    ctx = await _ctx(request, db,
        org=org_data,
        sources=sources,
        jobs=jobs,
        job_count=job_count,
        demographics=demographics,
    )

    return templates.TemplateResponse("orgs/detail.html", ctx)
