"""Pydantic schemas for JobPosting model."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict

if TYPE_CHECKING:
    from app.schemas.organization import OrganizationSummary


class JobPostingBase(BaseModel):
    """Base fields for job posting."""

    title: str
    application_url: str
    location: str | None = None
    city: str | None = None
    state: str | None = None
    category: str | None = None
    raw_category: str | None = None
    department: str | None = None
    employment_type: str | None = None
    salary_min: float | None = None
    salary_max: float | None = None
    salary_text: str | None = None
    posting_date: datetime | None = None
    closing_date: datetime | None = None
    description: str | None = None
    requirements: str | None = None


class JobPostingRead(JobPostingBase):
    """Full job posting output."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    source_id: UUID
    platform: str
    external_id: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    geocode_status: str | None = None
    extra_data: dict[str, Any] | None = None
    first_seen_at: datetime
    last_seen_at: datetime
    is_active: bool
    created_at: datetime
    updated_at: datetime


class JobPostingSummary(BaseModel):
    """Minimal job info for list views."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    title: str
    application_url: str
    organization_id: UUID
    platform: str
    city: str | None = None
    state: str | None = None
    category: str | None = None
    salary_text: str | None = None
    posting_date: datetime | None = None
    is_active: bool


class JobPostingWithOrg(JobPostingRead):
    """Job posting with embedded organization info."""

    organization: "OrganizationSummary | None" = None


class JobStats(BaseModel):
    """Aggregate job statistics."""

    total_jobs: int
    active_jobs: int
    by_platform: dict[str, int]
    by_category: dict[str, int]
    by_city: dict[str, int]
