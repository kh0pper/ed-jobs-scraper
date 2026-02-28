"""Saved jobs web routes."""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.base import get_db
from app.models.saved_job import SavedJob
from app.models.job_posting import JobPosting
from app.models.organization import Organization
from app.models.application import Application
from app.dependencies.auth import require_user, ensure_csrf_token
from app.models.user import User

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@router.get("/saved-jobs", response_class=HTMLResponse)
async def saved_jobs_list(
    request: Request,
    user: User = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    """List of user's saved jobs with notes."""
    result = await db.execute(
        select(SavedJob)
        .where(SavedJob.user_id == user.id)
        .options(selectinload(SavedJob.job_posting).selectinload(JobPosting.organization))
        .order_by(SavedJob.created_at.desc())
    )
    saved_jobs = result.scalars().all()

    # Get application statuses for saved jobs
    app_result = await db.execute(
        select(Application.job_posting_id, Application.status)
        .where(Application.user_id == user.id, Application.status != "failed")
    )
    application_statuses = {row[0]: row[1] for row in app_result}

    csrf_token = ensure_csrf_token(request)

    return templates.TemplateResponse(
        "saved_jobs/list.html",
        {
            "request": request,
            "current_user": user,
            "saved_jobs": saved_jobs,
            "application_statuses": application_statuses,
            "csrf_token": csrf_token,
        },
    )
