"""For You page — personalized job recommendations."""

from fastapi import APIRouter, Depends, Request, Query
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.base import get_db
from app.models.user import User
from app.models.user_interaction import UserInteraction
from app.models.saved_job import SavedJob
from app.dependencies.auth import require_user, ensure_csrf_token
from app.services.job_scoring_service import get_recommendations, COLD_START_THRESHOLD

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@router.get("/for-you", response_class=HTMLResponse)
async def for_you_page(
    request: Request,
    user: User = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    """Personalized job recommendations page."""
    # Count active interactions (not views)
    active_count_result = await db.execute(
        select(func.count(UserInteraction.id))
        .where(
            UserInteraction.user_id == user.id,
            UserInteraction.interaction_type.in_(["save", "thumbs_up", "thumbs_down", "apply_click"]),
        )
    )
    active_interaction_count = active_count_result.scalar() or 0
    is_cold_start = active_interaction_count < COLD_START_THRESHOLD

    # Get recommendations (first page)
    jobs, total = await get_recommendations(db, user.id, limit=20, offset=0)

    # Get saved job IDs for button state
    saved_result = await db.execute(
        select(SavedJob.job_posting_id).where(SavedJob.user_id == user.id)
    )
    saved_job_ids = {row[0] for row in saved_result}

    # Get user's thumbs state for displayed jobs
    job_ids = [j["id"] for j in jobs]
    user_thumbs = {}
    if job_ids:
        # Get most recent thumbs interaction per job
        for job_id in job_ids:
            result = await db.execute(
                select(UserInteraction.interaction_type)
                .where(
                    UserInteraction.user_id == user.id,
                    UserInteraction.job_posting_id == job_id,
                    UserInteraction.interaction_type.in_(["thumbs_up", "thumbs_down"]),
                )
                .order_by(UserInteraction.created_at.desc())
                .limit(1)
            )
            row = result.scalar_one_or_none()
            if row:
                user_thumbs[job_id] = row

    csrf_token = ensure_csrf_token(request)

    return templates.TemplateResponse(
        "for_you/index.html",
        {
            "request": request,
            "current_user": user,
            "jobs": jobs,
            "total": total,
            "is_cold_start": is_cold_start,
            "active_interaction_count": active_interaction_count,
            "cold_start_threshold": COLD_START_THRESHOLD,
            "saved_job_ids": saved_job_ids,
            "user_thumbs": user_thumbs,
            "csrf_token": csrf_token,
            "page": 1,
            "has_more": total > 20,
        },
    )


@router.get("/for-you/partial", response_class=HTMLResponse)
async def for_you_partial(
    request: Request,
    user: User = Depends(require_user),
    db: AsyncSession = Depends(get_db),
    page: int = Query(1, ge=1),
):
    """HTMX partial for paginated For You results."""
    limit = 20
    offset = (page - 1) * limit

    jobs, total = await get_recommendations(db, user.id, limit=limit, offset=offset)

    # Get saved job IDs
    saved_result = await db.execute(
        select(SavedJob.job_posting_id).where(SavedJob.user_id == user.id)
    )
    saved_job_ids = {row[0] for row in saved_result}

    # Get thumbs state
    job_ids = [j["id"] for j in jobs]
    user_thumbs = {}
    if job_ids:
        for job_id in job_ids:
            result = await db.execute(
                select(UserInteraction.interaction_type)
                .where(
                    UserInteraction.user_id == user.id,
                    UserInteraction.job_posting_id == job_id,
                    UserInteraction.interaction_type.in_(["thumbs_up", "thumbs_down"]),
                )
                .order_by(UserInteraction.created_at.desc())
                .limit(1)
            )
            row = result.scalar_one_or_none()
            if row:
                user_thumbs[job_id] = row

    has_more = (offset + limit) < total
    csrf_token = ensure_csrf_token(request)

    return templates.TemplateResponse(
        "partials/for_you_jobs.html",
        {
            "request": request,
            "current_user": user,
            "jobs": jobs,
            "saved_job_ids": saved_job_ids,
            "user_thumbs": user_thumbs,
            "csrf_token": csrf_token,
            "has_more": has_more,
            "page": page,
            "show_thumbs": True,
        },
    )
