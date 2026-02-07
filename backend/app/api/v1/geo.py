"""Geographic/proximity search API endpoints."""

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select, text
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
