"""HTMX interaction endpoints — save/unsave, notes, thumbs, apply-click."""

from uuid import UUID

from fastapi import APIRouter, Depends, Request, HTTPException
from fastapi.responses import HTMLResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.base import get_db
from app.models.saved_job import SavedJob
from app.models.user_interaction import UserInteraction
from app.models.user import User
from app.dependencies.auth import require_user_api, validate_csrf_token

router = APIRouter(prefix="/interactions", tags=["interactions"])
templates = Jinja2Templates(directory="app/templates")


def _check_csrf(request: Request):
    """Validate CSRF token from X-CSRF-Token header or form data."""
    token = request.headers.get("X-CSRF-Token", "")
    if not validate_csrf_token(request, token):
        raise HTTPException(status_code=403, detail="Invalid CSRF token")


# --- Save / Unsave ---

@router.post("/save/{job_id}", response_class=HTMLResponse)
async def save_job(
    request: Request,
    job_id: UUID,
    user: User = Depends(require_user_api),
    db: AsyncSession = Depends(get_db),
):
    """Save a job (bookmark). Returns updated save button partial."""
    _check_csrf(request)

    # Check if already saved
    existing = await db.execute(
        select(SavedJob).where(SavedJob.user_id == user.id, SavedJob.job_posting_id == job_id)
    )
    if existing.scalar_one_or_none():
        # Already saved — return filled state
        return templates.TemplateResponse(
            "partials/save_button.html",
            {"request": request, "job_id": job_id, "is_saved": True, "csrf_token": request.session.get("csrf_token", "")},
        )

    saved = SavedJob(user_id=user.id, job_posting_id=job_id)
    db.add(saved)

    # Record interaction
    interaction = UserInteraction(user_id=user.id, job_posting_id=job_id, interaction_type="save")
    db.add(interaction)
    await db.flush()

    # Fire profile update task
    _fire_profile_update(user.id)

    return templates.TemplateResponse(
        "partials/save_button.html",
        {"request": request, "job_id": job_id, "is_saved": True, "csrf_token": request.session.get("csrf_token", "")},
    )


@router.delete("/save/{job_id}", response_class=HTMLResponse)
async def unsave_job(
    request: Request,
    job_id: UUID,
    user: User = Depends(require_user_api),
    db: AsyncSession = Depends(get_db),
):
    """Unsave a job. Returns updated save button partial."""
    _check_csrf(request)

    await db.execute(
        delete(SavedJob).where(SavedJob.user_id == user.id, SavedJob.job_posting_id == job_id)
    )

    # Record interaction
    interaction = UserInteraction(user_id=user.id, job_posting_id=job_id, interaction_type="unsave")
    db.add(interaction)
    await db.flush()

    _fire_profile_update(user.id)

    return templates.TemplateResponse(
        "partials/save_button.html",
        {"request": request, "job_id": job_id, "is_saved": False, "csrf_token": request.session.get("csrf_token", "")},
    )


# --- Notes ---

@router.put("/save/{job_id}/notes", response_class=HTMLResponse)
async def update_notes(
    request: Request,
    job_id: UUID,
    user: User = Depends(require_user_api),
    db: AsyncSession = Depends(get_db),
):
    """Update notes on a saved job."""
    _check_csrf(request)

    form = await request.form()
    notes = form.get("notes", "").strip()

    result = await db.execute(
        select(SavedJob).where(SavedJob.user_id == user.id, SavedJob.job_posting_id == job_id)
    )
    saved = result.scalar_one_or_none()
    if not saved:
        raise HTTPException(status_code=404, detail="Job not saved")

    saved.notes = notes if notes else None
    await db.flush()

    return HTMLResponse(
        f'<span class="text-xs text-success">Saved</span>',
        status_code=200,
    )


# --- Thumbs up/down ---

@router.post("/thumbs/{job_id}/{direction}", response_class=HTMLResponse)
async def thumbs_vote(
    request: Request,
    job_id: UUID,
    direction: str,
    user: User = Depends(require_user_api),
    db: AsyncSession = Depends(get_db),
):
    """Toggle thumbs up/down. Returns updated thumbs buttons partial."""
    _check_csrf(request)

    if direction not in ("up", "down"):
        raise HTTPException(status_code=400, detail="Direction must be 'up' or 'down'")

    interaction_type = f"thumbs_{direction}"

    # Check most recent thumbs interaction for this (user, job) pair
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
    last_thumbs = result.scalar_one_or_none()

    if last_thumbs == interaction_type:
        # Same direction → toggle off (record removal, show neutral)
        active_thumb = None
    else:
        # Different or new → record new interaction
        new_interaction = UserInteraction(
            user_id=user.id, job_posting_id=job_id, interaction_type=interaction_type
        )
        db.add(new_interaction)
        await db.flush()
        active_thumb = interaction_type

    _fire_profile_update(user.id)

    return templates.TemplateResponse(
        "partials/thumbs_buttons.html",
        {
            "request": request,
            "job_id": job_id,
            "active_thumb": active_thumb,
            "csrf_token": request.session.get("csrf_token", ""),
        },
    )


# --- Apply click ---

@router.post("/apply-click/{job_id}")
async def apply_click(
    request: Request,
    job_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """Record an apply-click interaction. Returns 204. Works even if not logged in."""
    user_id = request.session.get("user_id")
    if not user_id:
        return Response(status_code=204)

    # Validate CSRF
    token = request.headers.get("X-CSRF-Token", "")
    if not validate_csrf_token(request, token):
        return Response(status_code=204)  # Silently fail for tracking endpoints

    interaction = UserInteraction(
        user_id=user_id, job_posting_id=job_id, interaction_type="apply_click"
    )
    db.add(interaction)
    await db.flush()

    _fire_profile_update(user_id)

    return Response(status_code=204)


def _fire_profile_update(user_id):
    """Dispatch Celery task to update user interest profile."""
    try:
        from app.tasks.profile_tasks import update_user_profile
        update_user_profile.delay(str(user_id))
    except Exception:
        pass  # Don't fail the request if Celery is down
