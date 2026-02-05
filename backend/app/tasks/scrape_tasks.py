"""Scrape orchestration tasks."""

import logging
from datetime import datetime, timezone, timedelta

from app.tasks.celery_app import celery_app
from app.models.base import SyncSessionLocal
from app.models.organization import Organization  # noqa: F401
from app.models.scrape_source import ScrapeSource
from app.models.job_posting import JobPosting  # noqa: F401
from app.models.scrape_run import ScrapeRun  # noqa: F401

logger = logging.getLogger(__name__)


@celery_app.task(name="app.tasks.scrape_tasks.dispatch_due_scrapes")
def dispatch_due_scrapes():
    """Find sources due for refresh and dispatch individual scrape tasks."""
    db = SyncSessionLocal()
    try:
        now = datetime.now(timezone.utc)

        sources = db.query(ScrapeSource).filter(
            ScrapeSource.is_active == True,  # noqa: E712
        ).all()

        dispatched = 0
        for source in sources:
            # Check if source is due for scraping
            if source.last_scraped_at:
                next_scrape = source.last_scraped_at + timedelta(minutes=source.scrape_frequency_minutes)
                if now < next_scrape:
                    continue

            # Dispatch individual scrape task
            scrape_source.delay(str(source.id))
            dispatched += 1

        logger.info(f"Dispatched {dispatched} scrape tasks")
        return {"dispatched": dispatched}

    finally:
        db.close()


@celery_app.task(name="app.tasks.scrape_tasks.scrape_source")
def scrape_source(source_id: str):
    """Scrape a single source. Looks up the platform and delegates to the appropriate scraper."""
    import uuid

    db = SyncSessionLocal()
    try:
        source = db.query(ScrapeSource).filter(ScrapeSource.id == source_id).first()
        if not source:
            logger.error(f"Source {source_id} not found")
            return

        # Create scrape run record
        run = ScrapeRun(
            id=uuid.uuid4(),
            source_id=source.id,
            started_at=datetime.now(timezone.utc),
            status="running",
        )
        db.add(run)
        db.commit()

        try:
            # Import scrapers package to trigger @register_scraper decorators
            import app.scrapers  # noqa: F401
            from app.scrapers.registry import get_scraper_class
            scraper_class = get_scraper_class(source.platform)

            if not scraper_class:
                raise ValueError(f"No scraper registered for platform: {source.platform}")

            scraper = scraper_class(source=source, db=db)
            results = scraper.run()

            # Update run record
            run.status = "success"
            run.finished_at = datetime.now(timezone.utc)
            run.jobs_found = results.get("jobs_found", 0)
            run.jobs_new = results.get("jobs_new", 0)
            run.jobs_updated = results.get("jobs_updated", 0)

            # Update source state
            source.last_scraped_at = datetime.now(timezone.utc)
            source.last_success_at = datetime.now(timezone.utc)
            source.last_job_count = results.get("jobs_found", 0)
            source.consecutive_failures = 0

            db.commit()
            logger.info(f"Scraped {source.platform}/{source.slug}: {results}")

        except Exception as e:
            run.status = "failed"
            run.finished_at = datetime.now(timezone.utc)
            run.error_message = str(e)[:2000]

            source.last_scraped_at = datetime.now(timezone.utc)
            source.consecutive_failures = (source.consecutive_failures or 0) + 1

            db.commit()
            logger.error(f"Failed to scrape {source.platform}/{source.slug}: {e}")

    finally:
        db.close()
