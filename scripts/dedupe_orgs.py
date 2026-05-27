"""Merge duplicate organization rows.

Handles the case where a manually-seeded org (tea_id=NULL) has
scrape_sources and job_postings that should belong to the TEA-seeded
counterpart. Moves all child rows then deletes the orphan.

Verified merge candidates as of 2026-05-27:
  - KIPP Texas Public Schools: tea_id=227820 (canonical) <-- tea_id=NULL (duplicate)

Usage:
    docker compose exec backend python -m scripts.dedupe_orgs --dry-run
    docker compose exec backend python -m scripts.dedupe_orgs
"""
import argparse
import logging

from app.models.base import SyncSessionLocal
from app.models.organization import Organization
from app.models.scrape_source import ScrapeSource
from app.models.job_posting import JobPosting
from app.models.scrape_run import ScrapeRun  # noqa: F401

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

MERGE_GROUPS = [
    {
        "description": "KIPP Texas Public Schools",
        "canonical_tea_id": "227820",
        "duplicate_name": "KIPP Texas Public Schools",
        "duplicate_tea_id": None,
    },
]


def dedupe(dry_run: bool = False):
    db = SyncSessionLocal()
    try:
        for group in MERGE_GROUPS:
            desc = group["description"]
            logger.info("Processing merge group: %s", desc)

            canonical = db.query(Organization).filter(
                Organization.tea_id == group["canonical_tea_id"]
            ).first()
            if not canonical:
                logger.warning("  Canonical org tea_id=%s not found, skipping", group["canonical_tea_id"])
                continue

            dup_query = db.query(Organization).filter(
                Organization.name.ilike(group["duplicate_name"]),
                Organization.id != canonical.id,
            )
            if group["duplicate_tea_id"] is None:
                dup_query = dup_query.filter(Organization.tea_id.is_(None))
            else:
                dup_query = dup_query.filter(Organization.tea_id == group["duplicate_tea_id"])

            dup = dup_query.first()
            if not dup:
                logger.info("  Duplicate not found (already merged?), skipping")
                continue

            sources = db.query(ScrapeSource).filter(ScrapeSource.organization_id == dup.id).all()
            jobs = db.query(JobPosting).filter(JobPosting.organization_id == dup.id).all()

            logger.info("  Canonical: %s (id=%s, tea_id=%s)", canonical.name, canonical.id, canonical.tea_id)
            logger.info("  Duplicate: %s (id=%s, tea_id=%s)", dup.name, dup.id, dup.tea_id)
            logger.info("  Sources to move: %d", len(sources))
            logger.info("  Jobs to move:    %d", len(jobs))

            if dry_run:
                logger.info("  (Dry run — no changes)")
                continue

            for s in sources:
                s.organization_id = canonical.id
            for j in jobs:
                j.organization_id = canonical.id

            canonical.platform_status = "mapped"
            db.flush()

            db.delete(dup)
            db.commit()

            logger.info("  MERGED: %d sources + %d jobs moved, duplicate deleted", len(sources), len(jobs))

        logger.info("Done")
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Merge duplicate organization rows")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()
    dedupe(dry_run=args.dry_run)
