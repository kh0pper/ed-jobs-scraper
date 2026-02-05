"""Pydantic schemas for Organization model."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class OrganizationBase(BaseModel):
    """Base fields for organization."""

    name: str
    org_type: str
    tea_id: str | None = None
    esc_region: int | None = None
    county: str | None = None
    city: str | None = None
    state: str = "TX"
    website_url: str | None = None
    total_students: int | None = None
    district_type: str | None = None
    charter_status: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    platform_status: str = "unmapped"


class OrganizationCreate(OrganizationBase):
    """Fields for creating an organization."""

    slug: str


class OrganizationRead(OrganizationBase):
    """Full organization output."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    slug: str
    created_at: datetime
    updated_at: datetime


class OrganizationSummary(BaseModel):
    """Minimal organization info for nested responses."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    slug: str
    org_type: str
    city: str | None = None
    esc_region: int | None = None


class OrganizationWithStats(OrganizationRead):
    """Organization with job/source counts."""

    source_count: int = 0
    active_job_count: int = 0
