"""Backfill attachments JSONB from existing description text.

Scans active job_postings that have a description containing PDF URLs
and populates the attachments column with extracted links.

Usage:
    docker compose exec backend python -m scripts.backfill_attachments
    docker compose exec backend python -m scripts.backfill_attachments --dry-run
"""

import argparse
import re
import logging

from app.models.base import SyncSessionLocal
from app.models.organization import Organization  # noqa: F401
from app.models.scrape_source import ScrapeSource  # noqa: F401
from app.models.job_posting import JobPosting
from app.models.scrape_run import ScrapeRun  # noqa: F401

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

PDF_URL_PATTERN = re.compile(
    r'(https?://[^\s<>"\']+\.pdf(?:\?[^\s<>"\']*)?)',
    re.IGNORECASE,
)

SALARY_KEYWORDS = ("salary schedule", "compensation schedule", "pay schedule", "salary scale", "pay scale")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    db = SyncSessionLocal()
    try:
        rows = (
            db.query(JobPosting)
            .filter(
                JobPosting.is_active.is_(True),
                JobPosting.description.isnot(None),
                JobPosting.description.like("%.pdf%"),
                JobPosting.attachments == [],
            )
            .all()
        )
        logger.info("Found %d rows with .pdf in description and empty attachments", len(rows))

        updated = 0
        for row in rows:
            urls = PDF_URL_PATTERN.findall(row.description)
            if not urls:
                continue
            seen = set()
            attachments = []
            for url in urls:
                if url in seen:
                    continue
                seen.add(url)
                filename = url.split("/")[-1].split("?")[0][:100]
                desc_lower = row.description.lower()
                url_idx = desc_lower.find(url.lower())
                context = desc_lower[max(0, url_idx - 80):url_idx] if url_idx >= 0 else ""
                is_schedule = any(kw in context for kw in SALARY_KEYWORDS)
                attachments.append({
                    "url": url,
                    "type": "salary_schedule" if is_schedule else "pdf",
                    "filename": filename,
                })
            if attachments:
                if args.dry_run:
                    logger.info("WOULD SET %s: %d attachments", row.title[:50], len(attachments))
                else:
                    row.attachments = attachments
                    db.commit()
                updated += 1

        logger.info("Done: %d rows updated (of %d candidates)", updated, len(rows))
        if args.dry_run:
            logger.info("(dry run — no changes committed)")
    finally:
        db.close()


if __name__ == "__main__":
    main()
