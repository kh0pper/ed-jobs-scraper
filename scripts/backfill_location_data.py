#!/usr/bin/env python3
"""One-time script to backfill location data for existing records.

This script:
1. Backfills org cities from county seats
2. Parses city from existing job location strings
3. Inherits city from org for jobs without parseable city
4. Elevates SchoolSpring school names to campus field
5. Initializes last_seen_run_id for active jobs

Run from the backend directory:
    cd backend && python -m scripts.backfill_location_data
Or via Docker:
    docker compose exec celery_worker python /app/scripts/backfill_location_data.py
"""

import sys
from pathlib import Path

# Add backend to path when running as script
backend_dir = Path(__file__).resolve().parent.parent / "backend"
if backend_dir.exists():
    sys.path.insert(0, str(backend_dir))

from datetime import datetime, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.base import SyncSessionLocal
from app.models.organization import Organization
from app.models.job_posting import JobPosting
from app.models.scrape_run import ScrapeRun
from app.models.scrape_source import ScrapeSource  # noqa: F401
from app.services.city_resolver import get_county_seat, parse_city_from_location


def backfill_org_cities(db: Session) -> dict:
    """Step 1: Backfill org cities from county seats."""
    print("\n=== Step 1: Backfilling org cities from county seats ===")

    orgs = db.query(Organization).filter(
        Organization.city.is_(None),
        Organization.county.isnot(None),
    ).all()

    print(f"Found {len(orgs)} orgs without city but with county")

    updated = 0
    for org in orgs:
        city = get_county_seat(org.county)
        if city:
            org.city = city
            org.city_source = "county_seat"
            updated += 1

    db.commit()
    print(f"Updated {updated} organizations with county seat cities")
    return {"orgs_updated": updated}


def backfill_job_cities_from_location(db: Session, batch_size: int = 1000) -> dict:
    """Step 2: Parse city from existing job location strings."""
    print("\n=== Step 2: Parsing city from job location strings ===")

    total_updated = 0
    skipped = 0

    while True:
        # NOTE: We skip unparseable jobs via offset. The offset accumulates only
        # the count of jobs we couldn't parse (still have city IS NULL).
        jobs = db.query(JobPosting).filter(
            JobPosting.city.is_(None),
            JobPosting.location.isnot(None),
            JobPosting.is_active == True,  # noqa: E712
        ).offset(skipped).limit(batch_size).all()

        if not jobs:
            break

        batch_updated = 0
        batch_skipped = 0
        for job in jobs:
            city = parse_city_from_location(job.location)
            if city:
                job.city = city
                batch_updated += 1
            else:
                batch_skipped += 1

        db.commit()
        total_updated += batch_updated
        skipped += batch_skipped
        print(f"  Progress: {total_updated} updated, {skipped} skipped")

    print(f"Parsed city from location for {total_updated} jobs")
    return {"jobs_from_location": total_updated}


def backfill_job_cities_from_org(db: Session, batch_size: int = 1000) -> dict:
    """Step 3: Inherit city from org for jobs without parseable city."""
    print("\n=== Step 3: Inheriting city from organization ===")

    total_updated = 0

    while True:
        # Find jobs still without city, join with org that has city
        # NOTE: Don't use offset - the filter results change as we update
        jobs = db.query(JobPosting).join(
            Organization, JobPosting.organization_id == Organization.id
        ).filter(
            JobPosting.city.is_(None),
            JobPosting.is_active == True,  # noqa: E712
            Organization.city.isnot(None),
        ).limit(batch_size).all()

        if not jobs:
            break

        batch_updated = 0
        for job in jobs:
            # Get org's city
            org = db.query(Organization).filter(
                Organization.id == job.organization_id
            ).first()
            if org and org.city:
                job.city = org.city
                batch_updated += 1

        db.commit()
        total_updated += batch_updated
        print(f"  Progress: {total_updated} jobs updated so far")

    print(f"Inherited city from org for {total_updated} jobs")
    return {"jobs_from_org": total_updated}


def elevate_schoolspring_schools(db: Session) -> dict:
    """Step 4: Elevate SchoolSpring school names to campus field."""
    print("\n=== Step 4: Elevating SchoolSpring schools to campus ===")

    # SchoolSpring jobs have school stored in department field
    jobs = db.query(JobPosting).filter(
        JobPosting.platform == "schoolspring",
        JobPosting.department.isnot(None),
        JobPosting.campus.is_(None),
    ).all()

    print(f"Found {len(jobs)} SchoolSpring jobs with department to elevate")

    for job in jobs:
        job.campus = job.department
        job.department = None

    db.commit()
    print(f"Elevated school to campus for {len(jobs)} SchoolSpring jobs")
    return {"schoolspring_elevated": len(jobs)}


def initialize_last_seen_run_ids(db: Session) -> dict:
    """Step 5: Initialize last_seen_run_id for active jobs."""
    print("\n=== Step 5: Initializing last_seen_run_id for active jobs ===")

    # For each source, find the most recent successful run and set it on active jobs
    sources = db.query(ScrapeSource).filter(
        ScrapeSource.is_active == True,  # noqa: E712
    ).all()

    total_updated = 0
    for source in sources:
        # Get most recent successful run for this source
        latest_run = db.query(ScrapeRun).filter(
            ScrapeRun.source_id == source.id,
            ScrapeRun.status == "success",
        ).order_by(ScrapeRun.started_at.desc()).first()

        if not latest_run:
            continue

        # Update all active jobs from this source that don't have last_seen_run_id
        updated = db.query(JobPosting).filter(
            JobPosting.source_id == source.id,
            JobPosting.is_active == True,  # noqa: E712
            JobPosting.last_seen_run_id.is_(None),
        ).update({"last_seen_run_id": latest_run.id}, synchronize_session=False)

        total_updated += updated

    db.commit()
    print(f"Initialized last_seen_run_id for {total_updated} active jobs")
    return {"jobs_run_id_set": total_updated}


def main():
    """Run all backfill steps."""
    print("=" * 60)
    print("Location Data Backfill Script")
    print(f"Started at: {datetime.now(timezone.utc).isoformat()}")
    print("=" * 60)

    db = SyncSessionLocal()
    results = {}

    try:
        # Pre-backfill stats
        jobs_without_city = db.query(func.count(JobPosting.id)).filter(
            JobPosting.city.is_(None),
            JobPosting.is_active == True,  # noqa: E712
        ).scalar()
        orgs_without_city = db.query(func.count(Organization.id)).filter(
            Organization.city.is_(None),
        ).scalar()
        print(f"\nPre-backfill: {jobs_without_city} jobs without city, {orgs_without_city} orgs without city")

        # Run backfill steps
        results.update(backfill_org_cities(db))
        results.update(backfill_job_cities_from_location(db))
        results.update(backfill_job_cities_from_org(db))
        results.update(elevate_schoolspring_schools(db))
        results.update(initialize_last_seen_run_ids(db))

        # Post-backfill stats
        jobs_without_city_after = db.query(func.count(JobPosting.id)).filter(
            JobPosting.city.is_(None),
            JobPosting.is_active == True,  # noqa: E712
        ).scalar()
        orgs_without_city_after = db.query(func.count(Organization.id)).filter(
            Organization.city.is_(None),
        ).scalar()

        print("\n" + "=" * 60)
        print("BACKFILL COMPLETE")
        print("=" * 60)
        print(f"Post-backfill: {jobs_without_city_after} jobs without city, {orgs_without_city_after} orgs without city")
        print(f"Results: {results}")
        print(f"Finished at: {datetime.now(timezone.utc).isoformat()}")

        return results

    except Exception as e:
        db.rollback()
        print(f"\nERROR: Backfill failed: {e}")
        raise

    finally:
        db.close()


if __name__ == "__main__":
    main()
