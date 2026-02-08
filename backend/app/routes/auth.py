"""Authentication web routes — login, register, logout, change password."""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.base import get_db
from app.models.user import User
from app.services.auth_service import hash_password, verify_password
from app.dependencies.auth import (
    get_current_user,
    require_user,
    ensure_csrf_token,
    validate_csrf_token,
)

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, db: AsyncSession = Depends(get_db)):
    user = await get_current_user(request, db)
    if user:
        return RedirectResponse("/", status_code=303)
    csrf_token = ensure_csrf_token(request)
    return templates.TemplateResponse(
        "auth/login.html",
        {"request": request, "csrf_token": csrf_token, "error": None},
    )


@router.post("/login", response_class=HTMLResponse)
async def login_submit(request: Request, db: AsyncSession = Depends(get_db)):
    form = await request.form()
    email = form.get("email", "").strip().lower()
    password = form.get("password", "")
    submitted_token = form.get("csrf_token", "")

    if not validate_csrf_token(request, submitted_token):
        csrf_token = ensure_csrf_token(request)
        return templates.TemplateResponse(
            "auth/login.html",
            {"request": request, "csrf_token": csrf_token, "error": "Invalid request. Please try again."},
        )

    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()

    if not user or not verify_password(password, user.hashed_password):
        csrf_token = ensure_csrf_token(request)
        return templates.TemplateResponse(
            "auth/login.html",
            {"request": request, "csrf_token": csrf_token, "error": "Invalid email or password."},
        )

    if not user.is_active:
        csrf_token = ensure_csrf_token(request)
        return templates.TemplateResponse(
            "auth/login.html",
            {"request": request, "csrf_token": csrf_token, "error": "This account has been deactivated."},
        )

    # Set session
    request.session["user_id"] = str(user.id)
    user.last_login_at = datetime.now(timezone.utc)
    await db.commit()

    return RedirectResponse("/", status_code=303)


@router.get("/register", response_class=HTMLResponse)
async def register_page(request: Request, db: AsyncSession = Depends(get_db)):
    user = await get_current_user(request, db)
    if user:
        return RedirectResponse("/", status_code=303)
    csrf_token = ensure_csrf_token(request)
    return templates.TemplateResponse(
        "auth/register.html",
        {"request": request, "csrf_token": csrf_token, "error": None},
    )


@router.post("/register", response_class=HTMLResponse)
async def register_submit(request: Request, db: AsyncSession = Depends(get_db)):
    form = await request.form()
    email = form.get("email", "").strip().lower()
    display_name = form.get("display_name", "").strip()
    password = form.get("password", "")
    confirm = form.get("confirm_password", "")
    submitted_token = form.get("csrf_token", "")

    if not validate_csrf_token(request, submitted_token):
        csrf_token = ensure_csrf_token(request)
        return templates.TemplateResponse(
            "auth/register.html",
            {"request": request, "csrf_token": csrf_token, "error": "Invalid request. Please try again."},
        )

    # Validation
    if not email or not display_name or not password:
        csrf_token = ensure_csrf_token(request)
        return templates.TemplateResponse(
            "auth/register.html",
            {"request": request, "csrf_token": csrf_token, "error": "All fields are required."},
        )

    if len(password) < 8:
        csrf_token = ensure_csrf_token(request)
        return templates.TemplateResponse(
            "auth/register.html",
            {"request": request, "csrf_token": csrf_token, "error": "Password must be at least 8 characters."},
        )

    if password != confirm:
        csrf_token = ensure_csrf_token(request)
        return templates.TemplateResponse(
            "auth/register.html",
            {"request": request, "csrf_token": csrf_token, "error": "Passwords do not match."},
        )

    user = User(
        email=email,
        display_name=display_name,
        hashed_password=hash_password(password),
        last_login_at=datetime.now(timezone.utc),
    )
    db.add(user)

    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        csrf_token = ensure_csrf_token(request)
        return templates.TemplateResponse(
            "auth/register.html",
            {"request": request, "csrf_token": csrf_token, "error": "Email already registered."},
        )

    request.session["user_id"] = str(user.id)
    await db.commit()

    return RedirectResponse("/", status_code=303)


@router.post("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/", status_code=303)


@router.get("/account/password", response_class=HTMLResponse)
async def change_password_page(
    request: Request,
    user: User = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    csrf_token = ensure_csrf_token(request)
    return templates.TemplateResponse(
        "auth/change_password.html",
        {"request": request, "current_user": user, "csrf_token": csrf_token, "error": None, "success": None},
    )


@router.post("/account/password", response_class=HTMLResponse)
async def change_password_submit(
    request: Request,
    user: User = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    form = await request.form()
    current_password = form.get("current_password", "")
    new_password = form.get("new_password", "")
    confirm = form.get("confirm_password", "")
    submitted_token = form.get("csrf_token", "")

    csrf_token = ensure_csrf_token(request)
    ctx = {"request": request, "current_user": user, "csrf_token": csrf_token, "error": None, "success": None}

    if not validate_csrf_token(request, submitted_token):
        ctx["error"] = "Invalid request. Please try again."
        return templates.TemplateResponse("auth/change_password.html", ctx)

    if not verify_password(current_password, user.hashed_password):
        ctx["error"] = "Current password is incorrect."
        return templates.TemplateResponse("auth/change_password.html", ctx)

    if len(new_password) < 8:
        ctx["error"] = "New password must be at least 8 characters."
        return templates.TemplateResponse("auth/change_password.html", ctx)

    if new_password != confirm:
        ctx["error"] = "New passwords do not match."
        return templates.TemplateResponse("auth/change_password.html", ctx)

    user.hashed_password = hash_password(new_password)
    await db.commit()

    ctx["success"] = "Password updated successfully."
    return templates.TemplateResponse("auth/change_password.html", ctx)
