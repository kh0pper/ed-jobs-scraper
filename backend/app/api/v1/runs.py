"""Scrape run API endpoints."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.base import get_db
from app.models.scrape_run import ScrapeRun
from app.models.scrape_source import ScrapeSource
from app.schemas.scrape_run import ScrapeRunRead, ScrapeRunWithSource
from app.schemas.scrape_source import ScrapeSourceSummary

router = APIRouter(prefix="/runs", tags=["runs"])


@router.get("", response_model=list[ScrapeRunWithSource])
async def list_runs(
    db: AsyncSession = Depends(get_db),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    source_id: UUID | None = Query(None, description="Filter by source"),
    status: str | None = Query(None, description="Filter by status"),
):
    """List recent scrape runs."""
    query = select(ScrapeRun).options(selectinload(ScrapeRun.source))

    if source_id:
        query = query.where(ScrapeRun.source_id == source_id)
    if status:
        query = query.where(ScrapeRun.status == status)

    query = query.order_by(ScrapeRun.started_at.desc()).offset(skip).limit(limit)
    result = await db.execute(query)
    runs = result.scalars().all()

    return [
        ScrapeRunWithSource(
            **ScrapeRunRead.model_validate(run).model_dump(),
            source=ScrapeSourceSummary.model_validate(run.source) if run.source else None,
        )
        for run in runs
    ]


@router.get("/{run_id}", response_model=ScrapeRunWithSource)
async def get_run(
    run_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """Get a single scrape run."""
    query = (
        select(ScrapeRun)
        .options(selectinload(ScrapeRun.source))
        .where(ScrapeRun.id == run_id)
    )
    result = await db.execute(query)
    run = result.scalar_one_or_none()

    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    return ScrapeRunWithSource(
        **ScrapeRunRead.model_validate(run).model_dump(),
        source=ScrapeSourceSummary.model_validate(run.source) if run.source else None,
    )
