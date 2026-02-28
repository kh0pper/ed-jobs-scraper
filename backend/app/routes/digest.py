"""Digest preferences and management routes."""

import json
import logging

from fastapi import APIRouter, Depends, Form, Request, Query
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.base import get_db
from app.models.user import User
from app.models.digest_preference import DigestPreference
from app.dependencies.auth import require_user, ensure_csrf_token, validate_csrf_token

logger = logging.getLogger(__name__)

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@router.get("/digest/preferences", response_class=HTMLResponse)
async def digest_preferences_page(
    request: Request,
    user: User = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    """Digest settings page."""
    result = await db.execute(
        select(DigestPreference).where(DigestPreference.user_id == user.id)
    )
    pref = result.scalar_one_or_none()

    csrf_token = ensure_csrf_token(request)

    return templates.TemplateResponse("digest/preferences.html", {
        "request": request,
        "current_user": user,
        "csrf_token": csrf_token,
        "pref": pref,
    })


@router.post("/digest/preferences")
async def save_digest_preferences(
    request: Request,
    user: User = Depends(require_user),
    db: AsyncSession = Depends(get_db),
    csrf_token: str = Form(""),
    is_enabled: str = Form("off"),
    day_of_week: int = Form(1),
    max_jobs: int = Form(20),
    categories_json: str = Form(""),
    regions_json: str = Form(""),
):
    """Save digest preferences."""
    if not validate_csrf_token(request, csrf_token):
        return RedirectResponse("/digest/preferences", status_code=303)

    result = await db.execute(
        select(DigestPreference).where(DigestPreference.user_id == user.id)
    )
    pref = result.scalar_one_or_none()

    if not pref:
        pref = DigestPreference(user_id=user.id)
        db.add(pref)

    pref.is_enabled = is_enabled == "on"
    pref.day_of_week = day_of_week
    pref.max_jobs = max_jobs

    if categories_json:
        try:
            pref.categories = json.loads(categories_json)
        except json.JSONDecodeError:
            pass
    else:
        pref.categories = None

    if regions_json:
        try:
            pref.regions = json.loads(regions_json)
        except json.JSONDecodeError:
            pass
    else:
        pref.regions = None

    return RedirectResponse("/digest/preferences?saved=1", status_code=303)


@router.post("/digest/send-now")
async def send_digest_now(
    request: Request,
    user: User = Depends(require_user),
    csrf_token: str = Form(""),
):
    """Manually trigger a digest email for the current user."""
    if not validate_csrf_token(request, csrf_token):
        return RedirectResponse("/digest/preferences", status_code=303)

    from app.tasks.digest_tasks import send_user_digest
    send_user_digest.delay(str(user.id))

    return RedirectResponse("/digest/preferences?sent=1", status_code=303)


@router.get("/digest/unsubscribe")
async def unsubscribe(
    request: Request,
    token: str = Query(""),
    db: AsyncSession = Depends(get_db),
):
    """One-click unsubscribe (CAN-SPAM compliance) using signed token."""
    from itsdangerous import URLSafeSerializer, BadSignature
    from app.config import get_settings

    settings = get_settings()
    s = URLSafeSerializer(settings.secret_key, salt="digest-unsubscribe")

    try:
        user_id = s.loads(token)
    except BadSignature:
        return HTMLResponse(
            "<html><body style='font-family:Arial; text-align:center; padding:60px;'>"
            "<h2>Invalid Link</h2>"
            "<p>This unsubscribe link is invalid or expired.</p>"
            "<p><a href='/digest/preferences'>Manage preferences</a></p>"
            "</body></html>",
            status_code=400,
        )

    result = await db.execute(
        select(DigestPreference).where(DigestPreference.user_id == user_id)
    )
    pref = result.scalar_one_or_none()
    if pref:
        pref.is_enabled = False

    return HTMLResponse(
        "<html><body style='font-family:Arial; text-align:center; padding:60px;'>"
        "<h2>Unsubscribed</h2>"
        "<p>You've been unsubscribed from weekly digest emails.</p>"
        "<p><a href='/digest/preferences'>Manage preferences</a></p>"
        "</body></html>"
    )
