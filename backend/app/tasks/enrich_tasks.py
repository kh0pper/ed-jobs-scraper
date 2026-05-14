"""Background detail-page enrichment for scraped job postings.

Listings-only scrapers leave salary/description NULL for most rows. This
task selects pending applitrack rows in batches, fetches each detail page
via services.job_extractor, parses the salary text into salary_min/max,
and writes back. Each row gets one attempt per 7 days regardless of
outcome — re-attempts only after that cooldown.
"""
import logging
from datetime import datetime, timezone, timedelta

from app.tasks.celery_app import celery_app
from app.models.base import SyncSessionLocal
from app.models.organization import Organization  # noqa: F401
from app.models.scrape_source import ScrapeSource  # noqa: F401
from app.models.job_posting import JobPosting
from app.models.scrape_run import ScrapeRun  # noqa: F401
from app.services.job_extractor import (
    extract_job_details,
    extract_salary,
    parse_salary_range,
)

logger = logging.getLogger(__name__)

ENRICHMENT_RETRY_DAYS = 7
DEFAULT_BATCH_LIMIT = 50
SUPPORTED_PLATFORMS = ("applitrack", "smartrecruiters")


@celery_app.task(name="app.tasks.enrich_tasks.enrich_pending_jobs")
def enrich_pending_jobs(limit: int = DEFAULT_BATCH_LIMIT, platform: str = "applitrack"):
    """Fetch detail pages for up to `limit` pending rows and backfill fields.

    Pending = (description IS NULL) AND (enrichment_attempted_at IS NULL OR
              attempted_at < now() - 7 days).
    Returns a dict with counts by enrichment_status for observability.
    """
    if platform not in SUPPORTED_PLATFORMS:
        logger.warning("enrich_pending_jobs called with unsupported platform: %s", platform)
        return {"skipped": True, "reason": "unsupported_platform"}

    cutoff = datetime.now(timezone.utc) - timedelta(days=ENRICHMENT_RETRY_DAYS)
    counts = {
        "success": 0,
        "no_data": 0,
        "parse_error": 0,
        "http_error": 0,
        "selected": 0,
    }

    db = SyncSessionLocal()
    try:
        rows = (
            db.query(JobPosting)
            .filter(
                JobPosting.platform == platform,
                JobPosting.description.is_(None),
                JobPosting.is_active.is_(True),
                (JobPosting.enrichment_attempted_at.is_(None))
                | (JobPosting.enrichment_attempted_at < cutoff),
            )
            .order_by(JobPosting.first_seen_at.desc())
            .limit(limit)
            .all()
        )
        counts["selected"] = len(rows)
        logger.info("enrich_pending_jobs: selected %d rows for platform=%s", len(rows), platform)

        for row in rows:
            now = datetime.now(timezone.utc)
            try:
                result = extract_job_details(row)
            except Exception as e:
                logger.warning("enrich http_error id=%s url=%s err=%s", row.id, row.application_url, e)
                row.enrichment_status = "http_error"
                row.enrichment_attempted_at = now
                counts["http_error"] += 1
                db.commit()
                continue

            description = result.get("description")
            requirements = result.get("requirements")
            salary_text = result.get("salary_info")
            # Structured salary_info from the platform extractor; if the
            # platform returned a value, parse it with autodetect.
            smin_struct, smax_struct = parse_salary_range(salary_text) if salary_text else (None, None)

            # Fallback: when the structured field didn't give us a number,
            # scan the description body for a label-anchored snippet. The
            # extract_salary helper applies the right hourly hint per
            # label tier so Annual Salary windows don't get ×2080'd when
            # a later Hourly Rate label sits in the same paragraph.
            snippet_smin = snippet_smax = None
            snippet_text = None
            if (smin_struct is None and smax_struct is None) and description:
                snippet_smin, snippet_smax, snippet_text = extract_salary(description)

            final_smin = smin_struct if smin_struct is not None else snippet_smin
            final_smax = smax_struct if smax_struct is not None else snippet_smax
            final_text = salary_text or snippet_text

            if not description and not final_text:
                row.enrichment_status = "no_data"
                row.enrichment_attempted_at = now
                counts["no_data"] += 1
                db.commit()
                continue

            try:
                if description and not row.description:
                    row.description = description
                if requirements and not row.requirements:
                    row.requirements = requirements
                if final_text and not row.salary_text:
                    row.salary_text = final_text[:255]
                if final_smin is not None and row.salary_min is None:
                    row.salary_min = final_smin
                if final_smax is not None and row.salary_max is None:
                    row.salary_max = final_smax
                row.enrichment_status = "success"
                row.enrichment_attempted_at = now
                counts["success"] += 1
                db.commit()
            except Exception as e:
                logger.warning("enrich parse_error id=%s err=%s", row.id, e)
                db.rollback()
                # Re-fetch the row in a fresh transaction to mark the failure
                fresh = db.query(JobPosting).filter(JobPosting.id == row.id).first()
                if fresh is not None:
                    fresh.enrichment_status = "parse_error"
                    fresh.enrichment_attempted_at = now
                    db.commit()
                counts["parse_error"] += 1

        logger.info("enrich_pending_jobs done: %s", counts)
        return counts

    finally:
        db.close()


@celery_app.task(name="app.tasks.enrich_tasks.backfill_salary_from_descriptions")
def backfill_salary_from_descriptions(limit: int = 200, platform: str | None = None):
    """Re-parse salary_min/max from existing descriptions without re-fetching.

    Use after improving the salary detection logic, to retro-populate rows
    that were already enriched (description IS NOT NULL) but never got a
    salary value. No HTTP traffic, no updates to enrichment_attempted_at.
    """
    counts = {"selected": 0, "updated": 0, "no_match": 0}
    db = SyncSessionLocal()
    try:
        q = (
            db.query(JobPosting)
            .filter(
                JobPosting.description.isnot(None),
                JobPosting.salary_min.is_(None),
            )
        )
        if platform:
            q = q.filter(JobPosting.platform == platform)
        rows = q.limit(limit).all()
        counts["selected"] = len(rows)

        for row in rows:
            smin, smax, snippet = extract_salary(row.description)
            if snippet is None or (smin is None and smax is None):
                counts["no_match"] += 1
                continue
            if not row.salary_text:
                row.salary_text = snippet[:255]
            if smin is not None and row.salary_min is None:
                row.salary_min = smin
            if smax is not None and row.salary_max is None:
                row.salary_max = smax
            counts["updated"] += 1
            db.commit()

        logger.info("backfill_salary_from_descriptions done: %s", counts)
        return counts
    finally:
        db.close()
