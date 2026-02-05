"""Pydantic schemas package."""

from app.schemas.organization import (
    OrganizationBase,
    OrganizationCreate,
    OrganizationRead,
    OrganizationSummary,
    OrganizationWithStats,
)
from app.schemas.job_posting import (
    JobPostingBase,
    JobPostingRead,
    JobPostingSummary,
    JobPostingWithOrg,
    JobStats,
)
from app.schemas.scrape_source import (
    ScrapeSourceBase,
    ScrapeSourceCreate,
    ScrapeSourceRead,
    ScrapeSourceSummary,
    ScrapeSourceWithOrg,
    ScrapeSourceWithRuns,
    ManualScrapeResponse,
)
from app.schemas.scrape_run import (
    ScrapeRunBase,
    ScrapeRunRead,
    ScrapeRunSummary,
    ScrapeRunWithSource,
)

# Rebuild models to resolve forward references
JobPostingWithOrg.model_rebuild()
ScrapeSourceWithOrg.model_rebuild()
ScrapeSourceWithRuns.model_rebuild()
ScrapeRunWithSource.model_rebuild()

__all__ = [
    # Organization
    "OrganizationBase",
    "OrganizationCreate",
    "OrganizationRead",
    "OrganizationSummary",
    "OrganizationWithStats",
    # JobPosting
    "JobPostingBase",
    "JobPostingRead",
    "JobPostingSummary",
    "JobPostingWithOrg",
    "JobStats",
    # ScrapeSource
    "ScrapeSourceBase",
    "ScrapeSourceCreate",
    "ScrapeSourceRead",
    "ScrapeSourceSummary",
    "ScrapeSourceWithOrg",
    "ScrapeSourceWithRuns",
    "ManualScrapeResponse",
    # ScrapeRun
    "ScrapeRunBase",
    "ScrapeRunRead",
    "ScrapeRunSummary",
    "ScrapeRunWithSource",
]
