"""Reactivate inactive scrape_sources for orgs that were rediscovered by a
probe run.

The probe scripts (probe_applitrack, probe_schoolspring) historically
only created NEW sources — if a previously-deactivated row existed for
the (org, platform) tuple, they silently skipped it. After the
2026-05-01 mass-deactivation of 936 schoolspring sources, that meant
re-probing recovered the same tenants but didn't reactivate them.

This script reads HIT lines from a probe log and reactivates the
existing inactive row for each (org, platform), updating slug and
base_url in case the working slug differs from the historic one. Idempotent.

Usage:
    docker compose exec backend python -m scripts.discovery.reactivate_from_probe_log \
        --log /path/to/probe_log --platform schoolspring [--dry-run]
"""
import argparse
import logging
import re
import sys

from app.models.base import SyncSessionLocal
from app.models.organization import Organization
from app.models.scrape_source import ScrapeSource
from app.models.job_posting import JobPosting  # noqa: F401
from app.models.scrape_run import ScrapeRun  # noqa: F401

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

HIT_PATTERN = re.compile(r"HIT: .+? \(([0-9]{6})\) -> (\S+)")


PLATFORM_URL_BUILDERS = {
    "schoolspring": lambda slug: f"https://{slug}.schoolspring.com/",
    "applitrack": lambda slug: f"https://www.applitrack.com/{slug}/onlineapp/jobpostings/Output.asp?all=1",
}


def reactivate(log_path: str, platform: str, dry_run: bool = False):
    if platform not in PLATFORM_URL_BUILDERS:
        sys.exit(f"unknown platform: {platform}")
    build_url = PLATFORM_URL_BUILDERS[platform]

    # Parse last-occurrence per tea_id (handles dedup if a log has retries)
    pairs: dict[str, str] = {}
    with open(log_path) as f:
        for line in f:
            m = HIT_PATTERN.search(line)
            if m:
                pairs[m.group(1)] = m.group(2)
    logger.info("Parsed %d unique HIT (tea_id, slug) pairs from %s", len(pairs), log_path)

    db = SyncSessionLocal()
    try:
        counts = {"reactivated": 0, "skipped_active": 0, "skipped_no_org": 0,
                  "skipped_no_source": 0, "slug_changed": 0}

        for tea_id, slug in pairs.items():
            org = db.query(Organization).filter(Organization.tea_id == tea_id).first()
            if not org:
                counts["skipped_no_org"] += 1
                continue

            source = (
                db.query(ScrapeSource)
                .filter(
                    ScrapeSource.organization_id == org.id,
                    ScrapeSource.platform == platform,
                )
                .first()
            )
            if not source:
                # Probe created a new one (or never had one) — nothing to do.
                counts["skipped_no_source"] += 1
                continue

            if source.is_active:
                counts["skipped_active"] += 1
                continue

            new_url = build_url(slug)
            old_slug = source.slug
            if dry_run:
                logger.info(
                    "  WOULD reactivate: %s (%s)  slug %s -> %s",
                    org.name, tea_id, old_slug, slug,
                )
            else:
                source.is_active = True
                if source.slug != slug:
                    counts["slug_changed"] += 1
                source.slug = slug
                source.base_url = new_url
                source.consecutive_failures = 0
                org.platform_status = "mapped"
                db.commit()
                logger.info("  REACTIVATED: %s (%s) -> %s", org.name, tea_id, slug)
            counts["reactivated"] += 1

        logger.info("Done: %s", counts)
        if dry_run:
            logger.info("(Dry run — no changes saved)")
    finally:
        db.close()


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Reactivate inactive sources rediscovered by a probe run")
    p.add_argument("--log", required=True, help="Path to probe log file")
    p.add_argument("--platform", required=True, choices=list(PLATFORM_URL_BUILDERS.keys()))
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()
    reactivate(args.log, args.platform, dry_run=args.dry_run)
