"""Maintenance tasks — staleness, cleanup, geocoding, dedup."""

import logging
from datetime import datetime, timezone, timedelta

from app.tasks.celery_app import celery_app
from app.models.base import SyncSessionLocal
from app.models.job_posting import JobPosting
from app.models.scrape_run import ScrapeRun

logger = logging.getLogger(__name__)


@celery_app.task(name="app.tasks.maintenance_tasks.mark_stale_postings")
def mark_stale_postings():
    """Mark jobs not seen in 14 days as inactive."""
    db = SyncSessionLocal()
    try:
        cutoff = datetime.now(timezone.utc) - timedelta(days=14)
        result = db.query(JobPosting).filter(
            JobPosting.is_active == True,  # noqa: E712
            JobPosting.last_seen_at < cutoff,
        ).update({"is_active": False}, synchronize_session=False)
        db.commit()
        logger.info(f"Marked {result} postings as stale")
        return {"marked_stale": result}
    finally:
        db.close()


@celery_app.task(name="app.tasks.maintenance_tasks.cleanup_old_postings")
def cleanup_old_postings():
    """Remove inactive postings older than 90 days."""
    db = SyncSessionLocal()
    try:
        cutoff = datetime.now(timezone.utc) - timedelta(days=90)
        result = db.query(JobPosting).filter(
            JobPosting.is_active == False,  # noqa: E712
            JobPosting.last_seen_at < cutoff,
        ).delete(synchronize_session=False)
        db.commit()
        logger.info(f"Deleted {result} old inactive postings")
        return {"deleted": result}
    finally:
        db.close()


@celery_app.task(name="app.tasks.maintenance_tasks.geocode_pending")
def geocode_pending():
    """Batch geocode up to 50 new postings."""
    # TODO: Implement geocoding service (Phase 5)
    logger.info("Geocoding task placeholder — not yet implemented")
    return {"geocoded": 0}


@celery_app.task(name="app.tasks.maintenance_tasks.deduplicate_postings")
def deduplicate_postings():
    """Cross-platform dedup check using content_hash."""
    # TODO: Implement dedup service (Phase 5)
    logger.info("Dedup task placeholder — not yet implemented")
    return {"deduped": 0}


@celery_app.task(name="app.tasks.maintenance_tasks.close_orphaned_scrape_runs")
def close_orphaned_scrape_runs():
    """Close scrape_runs stuck in 'running' for more than 6 hours.

    Workers can die mid-scrape (OOM, crash, host freeze, network drop) without
    finalizing the run. Those rows sit in 'running' forever and skew any
    in-flight count. This sweep reclassifies them as 'failed' with an
    explanatory message; 6h is well past the task_time_limit (600s) so any
    legitimately-running scrape is excluded.
    """
    db = SyncSessionLocal()
    try:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=6)
        result = db.query(ScrapeRun).filter(
            ScrapeRun.status == "running",
            ScrapeRun.started_at < cutoff,
        ).update(
            {
                "status": "failed",
                "finished_at": ScrapeRun.started_at,
                "error_message": "orphaned (no completion record) — closed by close_orphaned_scrape_runs",
            },
            synchronize_session=False,
        )
        db.commit()
        logger.info(f"Closed {result} orphaned scrape_runs")
        return {"closed": result}
    finally:
        db.close()
