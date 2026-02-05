"""Pydantic schemas for ScrapeSource model."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict

if TYPE_CHECKING:
    from app.schemas.organization import OrganizationSummary
    from app.schemas.scrape_run import ScrapeRunSummary


class ScrapeSourceBase(BaseModel):
    """Base fields for scrape source."""

    platform: str
    base_url: str
    slug: str | None = None
    is_active: bool = True
    scrape_frequency_minutes: int = 360
    config_json: dict[str, Any] | None = None
    discovered_by: str = "manual"


class ScrapeSourceCreate(ScrapeSourceBase):
    """Fields for creating a scrape source."""

    organization_id: UUID


class ScrapeSourceRead(ScrapeSourceBase):
    """Full scrape source output."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    last_scraped_at: datetime | None = None
    last_success_at: datetime | None = None
    last_job_count: int = 0
    consecutive_failures: int = 0
    created_at: datetime
    updated_at: datetime


class ScrapeSourceSummary(BaseModel):
    """Minimal source info for nested responses."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    platform: str
    base_url: str
    is_active: bool
    last_job_count: int = 0


class ScrapeSourceWithOrg(ScrapeSourceRead):
    """Source with embedded organization info."""

    organization: "OrganizationSummary | None" = None


class ScrapeSourceWithRuns(ScrapeSourceRead):
    """Source with recent scrape runs."""

    recent_runs: list["ScrapeRunSummary"] = []


class ManualScrapeResponse(BaseModel):
    """Response from triggering a manual scrape."""

    message: str
    task_id: str
    source_id: UUID
