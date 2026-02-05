"""Scrape source API endpoints."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.base import get_db
from app.models.scrape_source import ScrapeSource
from app.models.scrape_run import ScrapeRun
from app.models.organization import Organization
from app.schemas.scrape_source import (
    ScrapeSourceRead,
    ScrapeSourceWithOrg,
    ScrapeSourceWithRuns,
    ManualScrapeResponse,
)
from app.schemas.scrape_run import ScrapeRunSummary
from app.schemas.organization import OrganizationSummary

router = APIRouter(prefix="/sources", tags=["sources"])


@router.get("", response_model=list[ScrapeSourceWithOrg])
async def list_sources(
    db: AsyncSession = Depends(get_db),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    platform: str | None = Query(None, description="Filter by platform"),
    is_active: bool | None = Query(None, description="Filter by active status"),
):
    """List scrape sources with organization info."""
    query = select(ScrapeSource).options(selectinload(ScrapeSource.organization))

    if platform:
        query = query.where(ScrapeSource.platform == platform)
    if is_active is not None:
        query = query.where(ScrapeSource.is_active == is_active)

    query = query.order_by(ScrapeSource.last_scraped_at.desc().nullslast()).offset(skip).limit(limit)
    result = await db.execute(query)
    sources = result.scalars().all()

    return [
        ScrapeSourceWithOrg(
            **ScrapeSourceRead.model_validate(source).model_dump(),
            organization=OrganizationSummary.model_validate(source.organization)
            if source.organization
            else None,
        )
        for source in sources
    ]


@router.get("/{source_id}", response_model=ScrapeSourceWithRuns)
async def get_source(
    source_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """Get a single source with recent scrape runs."""
    query = select(ScrapeSource).where(ScrapeSource.id == source_id)
    result = await db.execute(query)
    source = result.scalar_one_or_none()

    if not source:
        raise HTTPException(status_code=404, detail="Source not found")

    # Get recent runs
    runs_query = (
        select(ScrapeRun)
        .where(ScrapeRun.source_id == source_id)
        .order_by(ScrapeRun.started_at.desc())
        .limit(10)
    )
    runs_result = await db.execute(runs_query)
    runs = runs_result.scalars().all()

    return ScrapeSourceWithRuns(
        **ScrapeSourceRead.model_validate(source).model_dump(),
        recent_runs=[ScrapeRunSummary.model_validate(run) for run in runs],
    )


@router.post("/{source_id}/scrape", response_model=ManualScrapeResponse)
async def trigger_scrape(
    source_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """Trigger a manual scrape for a source."""
    # Verify source exists and is active
    query = select(ScrapeSource).where(ScrapeSource.id == source_id)
    result = await db.execute(query)
    source = result.scalar_one_or_none()

    if not source:
        raise HTTPException(status_code=404, detail="Source not found")

    if not source.is_active:
        raise HTTPException(status_code=400, detail="Source is not active")

    # Dispatch Celery task
    from app.tasks.scrape_tasks import scrape_source

    task = scrape_source.delay(str(source_id))

    return ManualScrapeResponse(
        message=f"Scrape task queued for {source.platform}",
        task_id=task.id,
        source_id=source_id,
    )
