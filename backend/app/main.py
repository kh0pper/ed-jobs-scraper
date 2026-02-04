"""FastAPI application entry point."""

import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone

import redis
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.config import get_settings
from app.models.base import engine, AsyncSessionLocal, Base

logger = logging.getLogger(__name__)
settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup and shutdown."""
    logger.info("Starting %s...", settings.app_name)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database tables verified")
    yield
    logger.info("Shutting down...")
    await engine.dispose()


app = FastAPI(
    title=settings.app_name,
    description="Job aggregation platform for Texas education positions",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health_check():
    return {"status": "healthy", "app": settings.app_name}


@app.get("/health/detailed")
async def detailed_health_check():
    checks = {}

    # Database
    try:
        async with AsyncSessionLocal() as session:
            result = await session.execute(text("SELECT 1"))
            result.scalar()
            checks["database"] = {"ok": True}
    except Exception as e:
        checks["database"] = {"ok": False, "message": str(e)}

    # Redis
    try:
        r = redis.from_url(settings.redis_url, socket_timeout=5)
        r.ping()
        checks["redis"] = {"ok": True}
    except Exception as e:
        checks["redis"] = {"ok": False, "message": str(e)}

    # Celery workers
    try:
        from app.tasks.celery_app import celery_app
        inspect = celery_app.control.inspect(timeout=5)
        active_workers = inspect.active()
        checks["celery_workers"] = {
            "ok": bool(active_workers),
            "workers": list(active_workers.keys()) if active_workers else [],
        }
    except Exception as e:
        checks["celery_workers"] = {"ok": False, "message": str(e)}

    all_ok = all(check.get("ok", False) for check in checks.values())
    status = "healthy" if all_ok else "degraded"

    return {
        "status": status,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "checks": checks,
    }
