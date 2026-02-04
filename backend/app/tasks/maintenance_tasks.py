"""Maintenance tasks — staleness, cleanup, geocoding, dedup."""

import logging
from datetime import datetime, timezone, timedelta

from app.tasks.celery_app import celery_app
from app.models.base import SyncSessionLocal
from app.models.job_posting import JobPosting

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
