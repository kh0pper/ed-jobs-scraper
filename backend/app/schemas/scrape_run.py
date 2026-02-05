"""Pydantic schemas for ScrapeRun model."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from pydantic import BaseModel, ConfigDict

if TYPE_CHECKING:
    from app.schemas.scrape_source import ScrapeSourceSummary


class ScrapeRunBase(BaseModel):
    """Base fields for scrape run."""

    started_at: datetime
    status: str = "running"


class ScrapeRunRead(ScrapeRunBase):
    """Full scrape run output."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    source_id: UUID
    finished_at: datetime | None = None
    jobs_found: int = 0
    jobs_new: int = 0
    jobs_updated: int = 0
    error_message: str | None = None


class ScrapeRunSummary(BaseModel):
    """Minimal run info for list views."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    source_id: UUID
    started_at: datetime
    finished_at: datetime | None = None
    status: str
    jobs_found: int = 0
    jobs_new: int = 0


class ScrapeRunWithSource(ScrapeRunRead):
    """Run with embedded source info."""

    source: "ScrapeSourceSummary | None" = None
