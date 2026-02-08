"""Authentication dependencies for FastAPI routes."""

import secrets

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.base import get_db
from app.models.user import User


class NotAuthenticatedException(Exception):
    """Raised when a route requires login but user is not authenticated."""
    pass


async def get_current_user(request: Request, db: AsyncSession = Depends(get_db)) -> User | None:
    """Return the logged-in user or None."""
    user_id = request.session.get("user_id")
    if not user_id:
        return None
    result = await db.execute(
        select(User).where(User.id == user_id, User.is_active == True)
    )
    return result.scalar_one_or_none()


async def require_user(request: Request, db: AsyncSession = Depends(get_db)) -> User:
    """Return the logged-in user or redirect to login."""
    user = await get_current_user(request, db)
    if not user:
        raise NotAuthenticatedException()
    return user


async def require_user_api(request: Request, db: AsyncSession = Depends(get_db)) -> User:
    """Return the logged-in user or raise 401 (for HTMX/API endpoints)."""
    user = await get_current_user(request, db)
    if not user:
        raise HTTPException(status_code=401, detail="Login required")
    return user


def ensure_csrf_token(request: Request) -> str:
    """Get or create a CSRF token in the session."""
    token = request.session.get("csrf_token")
    if not token:
        token = secrets.token_urlsafe(32)
        request.session["csrf_token"] = token
    return token


def validate_csrf_token(request: Request, token: str) -> bool:
    """Validate a submitted CSRF token against the session token."""
    session_token = request.session.get("csrf_token")
    if not session_token or not token:
        return False
    return secrets.compare_digest(session_token, token)
