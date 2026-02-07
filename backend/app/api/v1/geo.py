"""Geographic/proximity search API endpoints."""

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.base import get_db
from app.models.job_posting import JobPosting
from app.models.organization import Organization

router = APIRouter(prefix="/geo", tags=["geo"])


class JobGeoResult(BaseModel):
    """Job with geographic info for map display."""

    id: UUID
    title: str
    application_url: str
    organization_name: str
    city: str | None
    state: str | None
    latitude: float
    longitude: float
    platform: str


class GeoJSONFeature(BaseModel):
    """GeoJSON Feature for a job."""

    type: str = "Feature"
    geometry: dict[str, Any]
    properties: dict[str, Any]


class GeoJSONFeatureCollection(BaseModel):
    """GeoJSON FeatureCollection for map display."""

    type: str = "FeatureCollection"
    features: list[GeoJSONFeature]


def _escape_ilike(value: str) -> str:
    """Escape % and _ characters for use in ILIKE patterns."""
    return value.replace("%", r"\%").replace("_", r"\_")


@router.get("/jobs/nearby", response_model=list[JobGeoResult])
async def get_nearby_jobs(
    db: AsyncSession = Depends(get_db),
    lat: float = Query(..., ge=-90, le=90, description="Latitude of search center"),
    lon: float = Query(..., ge=-180, le=180, description="Longitude of search center"),
    radius: float = Query(25, ge=1, le=100, description="Search radius in miles"),
    limit: int = Query(100, ge=1, le=500, description="Maximum results to return"),
    active_only: bool = Query(True, description="Only return active jobs"),
):
    """
    Find jobs within a radius of a point.

    Uses PostGIS ST_DWithin for efficient spatial queries.
    Radius is in miles (converted to meters internally).
    """
    # Convert miles to meters
    radius_meters = radius * 1609.34

    # PostGIS query using geography type for accurate distance
    query = text("""
        SELECT
            j.id,
            j.title,
            j.application_url,
            o.name as organization_name,
            j.city,
            j.state,
            j.latitude,
            j.longitude,
            j.platform,
            ST_Distance(j.geog, ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography) as distance
        FROM job_postings j
        JOIN organizations o ON j.organization_id = o.id
        WHERE j.latitude IS NOT NULL
          AND j.longitude IS NOT NULL
          AND ST_DWithin(
              j.geog,
              ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography,
              :radius_meters
          )
          AND (:active_only = false OR j.is_active = true)
        ORDER BY distance
        LIMIT :limit
    """)

    result = await db.execute(
        query,
        {
            "lat": lat,
            "lon": lon,
            "radius_meters": radius_meters,
            "active_only": active_only,
            "limit": limit,
        },
    )

    jobs = []
    for row in result.mappings():
        jobs.append(
            JobGeoResult(
                id=row["id"],
                title=row["title"],
                application_url=row["application_url"],
                organization_name=row["organization_name"],
                city=row["city"],
                state=row["state"],
                latitude=row["latitude"],
                longitude=row["longitude"],
                platform=row["platform"],
            )
        )

    return jobs


@router.get("/jobs/geojson", response_model=GeoJSONFeatureCollection)
async def get_jobs_geojson(
    db: AsyncSession = Depends(get_db),
    limit: int = Query(1000, ge=1, le=5000, description="Maximum features to return"),
    active_only: bool = Query(True, description="Only return active jobs"),
    north: float | None = Query(None, ge=-90, le=90, description="Bounding box north"),
    south: float | None = Query(None, ge=-90, le=90, description="Bounding box south"),
    east: float | None = Query(None, ge=-180, le=180, description="Bounding box east"),
    west: float | None = Query(None, ge=-180, le=180, description="Bounding box west"),
    search: str | None = Query(None, description="Search job titles"),
    category: str | None = Query(None, description="Filter by category"),
    platform: str | None = Query(None, description="Filter by platform"),
    city: str | None = Query(None, description="Filter by city"),
):
    """
    Get jobs as GeoJSON FeatureCollection for map display.

    Optimized for Leaflet/Mapbox consumption with marker clustering.
    Supports optional bounding box and filter parameters.
    """
    query = (
        select(
            JobPosting.id,
            JobPosting.title,
            JobPosting.application_url,
            JobPosting.city,
            JobPosting.state,
            JobPosting.latitude,
            JobPosting.longitude,
            JobPosting.platform,
            JobPosting.category,
            Organization.name.label("organization_name"),
        )
        .join(Organization, JobPosting.organization_id == Organization.id)
        .where(JobPosting.latitude.isnot(None))
        .where(JobPosting.longitude.isnot(None))
    )

    if active_only:
        query = query.where(JobPosting.is_active == True)

    # Bounding box filter (all four required together)
    if north is not None and south is not None and east is not None and west is not None:
        query = query.where(
            JobPosting.latitude.between(south, north),
            JobPosting.longitude.between(west, east),
        )

    # Text filters
    if search:
        escaped = _escape_ilike(search)
        query = query.where(JobPosting.title.ilike(f"%{escaped}%"))
    if category:
        query = query.where(JobPosting.category == category)
    if platform:
        query = query.where(JobPosting.platform == platform)
    if city:
        escaped = _escape_ilike(city)
        query = query.where(JobPosting.city.ilike(f"%{escaped}%"))

    query = query.limit(limit)

    result = await db.execute(query)

    features = []
    for row in result.mappings():
        feature = GeoJSONFeature(
            geometry={
                "type": "Point",
                "coordinates": [row["longitude"], row["latitude"]],
            },
            properties={
                "id": str(row["id"]),
                "title": row["title"],
                "url": row["application_url"],
                "city": row["city"],
                "state": row["state"],
                "platform": row["platform"],
                "category": row["category"],
                "organization": row["organization_name"],
            },
        )
        features.append(feature)

    return GeoJSONFeatureCollection(features=features)


@router.get("/jobs/markers")
async def get_job_markers(
    db: AsyncSession = Depends(get_db),
    search: str | None = Query(None, description="Search job titles"),
    category: str | None = Query(None, description="Filter by category"),
    platform: str | None = Query(None, description="Filter by platform"),
    city: str | None = Query(None, description="Filter by city"),
    organization_id: str | None = Query(None, description="Filter by organization ID"),
    limit: int = Query(15000, ge=1, le=15000, description="Maximum markers"),
):
    """
    Compact marker data for map display.

    Returns flat [lat, lng, id] tuples instead of full GeoJSON — ~3x smaller payload.
    No bbox filtering: returns all matching geocoded jobs so the frontend can
    load once and only re-fetch when filters change.
    """
    query = (
        select(
            JobPosting.latitude,
            JobPosting.longitude,
            JobPosting.id,
        )
        .where(JobPosting.latitude.isnot(None))
        .where(JobPosting.longitude.isnot(None))
        .where(JobPosting.is_active == True)
    )

    if search:
        escaped = _escape_ilike(search)
        query = query.where(JobPosting.title.ilike(f"%{escaped}%"))
    if category:
        query = query.where(JobPosting.category == category)
    if platform:
        query = query.where(JobPosting.platform == platform)
    if city:
        escaped = _escape_ilike(city)
        query = query.where(JobPosting.city.ilike(f"%{escaped}%"))
    if organization_id:
        query = query.where(JobPosting.organization_id == organization_id)

    query = query.limit(limit)
    result = await db.execute(query)

    markers = [
        [float(row.latitude), float(row.longitude), str(row.id)]
        for row in result
    ]

    return JSONResponse(
        content={"markers": markers, "total": len(markers)},
        headers={"Cache-Control": "public, max-age=60"},
    )


@router.get("/jobs/{job_id}/popup")
async def get_job_popup(
    job_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """
    Lightweight popup data for a single job marker.

    Returns just the fields needed for the map popup — fetched on marker click.
    """
    query = (
        select(
            JobPosting.title,
            JobPosting.category,
            JobPosting.city,
            JobPosting.id,
            Organization.name.label("organization_name"),
        )
        .join(Organization, JobPosting.organization_id == Organization.id)
        .where(JobPosting.id == job_id)
        .where(JobPosting.is_active == True)
    )

    result = await db.execute(query)
    row = result.mappings().first()

    if not row:
        raise HTTPException(status_code=404, detail="Job not found")

    return {
        "title": row["title"],
        "organization": row["organization_name"],
        "category": row["category"],
        "city": row["city"],
        "detail_url": f"/jobs/{row['id']}",
    }


@router.get("/organizations/markers")
async def get_org_markers(
    db: AsyncSession = Depends(get_db),
    search: str | None = Query(None, description="Search org name"),
    org_type: str | None = Query(None, description="Filter by org type"),
    esc_region: int | None = Query(None, description="Filter by ESC region"),
    platform_status: str | None = Query(None, description="Filter by platform status"),
):
    """
    Compact org marker data for map display.
    Returns [lat, lng, id, tea_id, active_job_count] tuples.
    """
    # Subquery for active job counts
    job_count_sub = (
        select(
            JobPosting.organization_id,
            func.count(JobPosting.id).label("job_count"),
        )
        .where(JobPosting.is_active == True)
        .group_by(JobPosting.organization_id)
        .subquery()
    )

    query = (
        select(
            Organization.latitude,
            Organization.longitude,
            Organization.id,
            Organization.tea_id,
            func.coalesce(job_count_sub.c.job_count, 0).label("active_job_count"),
        )
        .outerjoin(job_count_sub, Organization.id == job_count_sub.c.organization_id)
        .where(Organization.latitude.isnot(None))
        .where(Organization.longitude.isnot(None))
    )

    if search:
        escaped = _escape_ilike(search)
        query = query.where(Organization.name.ilike(f"%{escaped}%"))
    if org_type:
        query = query.where(Organization.org_type == org_type)
    if esc_region:
        query = query.where(Organization.esc_region == esc_region)
    if platform_status:
        query = query.where(Organization.platform_status == platform_status)

    result = await db.execute(query)

    markers = [
        [float(row.latitude), float(row.longitude), str(row.id),
         row.tea_id, int(row.active_job_count)]
        for row in result
    ]

    return JSONResponse(
        content={"markers": markers, "total": len(markers)},
        headers={"Cache-Control": "public, max-age=60"},
    )


@router.get("/organizations/{org_id}/popup")
async def get_org_popup(
    org_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """Lightweight popup data for an organization marker."""
    query = (
        select(
            Organization.id,
            Organization.name,
            Organization.org_type,
            Organization.city,
            Organization.total_students,
            Organization.slug,
        )
        .where(Organization.id == org_id)
    )

    result = await db.execute(query)
    row = result.mappings().first()

    if not row:
        raise HTTPException(status_code=404, detail="Organization not found")

    # Get active job count
    job_count = (await db.execute(
        select(func.count(JobPosting.id))
        .where(JobPosting.organization_id == org_id)
        .where(JobPosting.is_active == True)
    )).scalar() or 0

    return {
        "name": row["name"],
        "org_type": row["org_type"],
        "city": row["city"],
        "total_students": row["total_students"],
        "active_jobs": job_count,
        "detail_url": f"/orgs/{row['id']}",
    }


@router.get("/organizations/nearby", response_model=list[dict])
async def get_nearby_organizations(
    db: AsyncSession = Depends(get_db),
    lat: float = Query(..., ge=-90, le=90, description="Latitude of search center"),
    lon: float = Query(..., ge=-180, le=180, description="Longitude of search center"),
    radius: float = Query(25, ge=1, le=100, description="Search radius in miles"),
    limit: int = Query(50, ge=1, le=200, description="Maximum results to return"),
):
    """
    Find organizations within a radius of a point.

    Useful for finding nearby school districts.
    """
    radius_meters = radius * 1609.34

    query = text("""
        SELECT
            id,
            name,
            slug,
            org_type,
            city,
            county,
            esc_region,
            total_students,
            latitude,
            longitude,
            platform_status,
            ST_Distance(geog, ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography) / 1609.34 as distance_miles
        FROM organizations
        WHERE latitude IS NOT NULL
          AND longitude IS NOT NULL
          AND ST_DWithin(
              geog,
              ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography,
              :radius_meters
          )
        ORDER BY distance_miles
        LIMIT :limit
    """)

    result = await db.execute(
        query,
        {"lat": lat, "lon": lon, "radius_meters": radius_meters, "limit": limit},
    )

    orgs = []
    for row in result.mappings():
        orgs.append(dict(row))

    return orgs
