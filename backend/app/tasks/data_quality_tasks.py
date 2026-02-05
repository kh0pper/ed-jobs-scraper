"""Data quality tasks for category normalization, geocoding, and state backfill."""

import logging
import re

from app.tasks.celery_app import celery_app
from app.models.base import SyncSessionLocal
from app.models.organization import Organization  # noqa: F401
from app.models.scrape_source import ScrapeSource  # noqa: F401
from app.models.job_posting import JobPosting
from app.models.scrape_run import ScrapeRun  # noqa: F401
from app.services.category_normalizer import normalize_category
from app.services.geocoder import Geocoder
from app.services.city_resolver import resolve_city_for_job, derive_org_city

logger = logging.getLogger(__name__)

# State abbreviations for parsing
US_STATES = {
    "ALABAMA": "AL", "ALASKA": "AK", "ARIZONA": "AZ", "ARKANSAS": "AR", "CALIFORNIA": "CA",
    "COLORADO": "CO", "CONNECTICUT": "CT", "DELAWARE": "DE", "FLORIDA": "FL", "GEORGIA": "GA",
    "HAWAII": "HI", "IDAHO": "ID", "ILLINOIS": "IL", "INDIANA": "IN", "IOWA": "IA",
    "KANSAS": "KS", "KENTUCKY": "KY", "LOUISIANA": "LA", "MAINE": "ME", "MARYLAND": "MD",
    "MASSACHUSETTS": "MA", "MICHIGAN": "MI", "MINNESOTA": "MN", "MISSISSIPPI": "MS", "MISSOURI": "MO",
    "MONTANA": "MT", "NEBRASKA": "NE", "NEVADA": "NV", "NEW HAMPSHIRE": "NH", "NEW JERSEY": "NJ",
    "NEW MEXICO": "NM", "NEW YORK": "NY", "NORTH CAROLINA": "NC", "NORTH DAKOTA": "ND", "OHIO": "OH",
    "OKLAHOMA": "OK", "OREGON": "OR", "PENNSYLVANIA": "PA", "RHODE ISLAND": "RI", "SOUTH CAROLINA": "SC",
    "SOUTH DAKOTA": "SD", "TENNESSEE": "TN", "TEXAS": "TX", "UTAH": "UT", "VERMONT": "VT",
    "VIRGINIA": "VA", "WASHINGTON": "WA", "WEST VIRGINIA": "WV", "WISCONSIN": "WI", "WYOMING": "WY",
    "DISTRICT OF COLUMBIA": "DC",
}
STATE_ABBREVS = set(US_STATES.values())


def parse_state_from_location(location: str | None) -> str | None:
    """Parse state from location string like 'Houston, TX' or 'Texas'."""
    if not location:
        return None
    text = location.strip().upper()
    # Check for 2-letter state at end: "Houston, TX" or "Houston TX"
    match = re.search(r"\b([A-Z]{2})\s*$", text)
    if match and match.group(1) in STATE_ABBREVS:
        return match.group(1)
    # Check for full state name
    for name, abbrev in US_STATES.items():
        if name in text:
            return abbrev
    return None


@celery_app.task(name="app.tasks.data_quality_tasks.normalize_job_categories")
def normalize_job_categories(batch_size: int = 500):
    """
    Normalize categories for job postings that don't have one.

    Runs periodically to process newly scraped jobs.
    """
    db = SyncSessionLocal()
    try:
        # Find jobs without normalized category
        jobs = db.query(JobPosting).filter(
            JobPosting.category.is_(None),
            JobPosting.is_active == True,  # noqa: E712
        ).limit(batch_size).all()

        if not jobs:
            logger.info("No jobs need category normalization")
            return {"processed": 0}

        updated = 0
        for job in jobs:
            category = normalize_category(job.title, job.raw_category)
            if category:
                job.category = category
                updated += 1

        db.commit()
        logger.info(f"Normalized categories for {updated} jobs")
        return {"processed": updated}

    except Exception as e:
        db.rollback()
        logger.error(f"Category normalization failed: {e}")
        raise

    finally:
        db.close()


@celery_app.task(name="app.tasks.data_quality_tasks.geocode_pending_jobs")
def geocode_pending_jobs(batch_size: int = 50):
    """
    Geocode job postings that don't have coordinates.

    Limited batch size due to Nominatim rate limits (1 req/sec).
    """
    db = SyncSessionLocal()
    geocoder = Geocoder(rate_limit=1.0)

    try:
        # Find jobs needing geocoding (have city but no coordinates)
        jobs = db.query(JobPosting).filter(
            JobPosting.geocode_status == "pending",
            JobPosting.is_active == True,  # noqa: E712
            JobPosting.city.isnot(None),
        ).limit(batch_size).all()

        if not jobs:
            logger.info("No jobs need geocoding")
            return {"processed": 0, "success": 0, "failed": 0}

        success = 0
        failed = 0

        for job in jobs:
            try:
                result = geocoder.geocode_sync(
                    query=job.city,
                    city=job.city,
                    state="Texas",
                )

                if result:
                    job.latitude = result.latitude
                    job.longitude = result.longitude
                    job.geocode_status = "success"
                    success += 1
                else:
                    job.geocode_status = "failed"
                    failed += 1

            except Exception as e:
                logger.warning(f"Geocoding failed for job {job.id}: {e}")
                job.geocode_status = "failed"
                failed += 1

        db.commit()
        logger.info(f"Geocoded {success} jobs, {failed} failed")
        return {"processed": success + failed, "success": success, "failed": failed}

    except Exception as e:
        db.rollback()
        logger.error(f"Geocoding batch failed: {e}")
        raise

    finally:
        db.close()


@celery_app.task(name="app.tasks.data_quality_tasks.geocode_pending_organizations")
def geocode_pending_organizations(batch_size: int = 50):
    """
    Geocode organizations that don't have coordinates.
    """
    db = SyncSessionLocal()
    geocoder = Geocoder(rate_limit=1.0)

    try:
        # Find orgs needing geocoding
        orgs = db.query(Organization).filter(
            Organization.latitude.is_(None),
            Organization.longitude.is_(None),
        ).limit(batch_size).all()

        if not orgs:
            logger.info("No organizations need geocoding")
            return {"processed": 0, "success": 0, "failed": 0}

        success = 0
        failed = 0

        for org in orgs:
            try:
                # Try geocoding with org name and city/county
                result = geocoder.geocode_sync(
                    query=org.name,
                    city=org.city,
                    state="Texas",
                )

                # If that fails, try with county
                if not result and org.county:
                    result = geocoder.geocode_sync(
                        query=f"{org.name}, {org.county} County",
                        state="Texas",
                    )

                if result:
                    org.latitude = result.latitude
                    org.longitude = result.longitude
                    success += 1
                else:
                    failed += 1

            except Exception as e:
                logger.warning(f"Geocoding failed for org {org.name}: {e}")
                failed += 1

        db.commit()
        logger.info(f"Geocoded {success} organizations, {failed} failed")
        return {"processed": success + failed, "success": success, "failed": failed}

    except Exception as e:
        db.rollback()
        logger.error(f"Organization geocoding batch failed: {e}")
        raise

    finally:
        db.close()


@celery_app.task(name="app.tasks.data_quality_tasks.backfill_all_categories")
def backfill_all_categories():
    """
    One-time task to normalize all existing job categories.
    Processes in batches to avoid memory issues.
    """
    db = SyncSessionLocal()
    total_updated = 0
    batch_size = 1000

    try:
        while True:
            jobs = db.query(JobPosting).filter(
                JobPosting.category.is_(None),
            ).limit(batch_size).all()

            if not jobs:
                break

            for job in jobs:
                category = normalize_category(job.title, job.raw_category)
                if category:
                    job.category = category
                    total_updated += 1

            db.commit()
            logger.info(f"Backfill progress: {total_updated} jobs normalized")

        logger.info(f"Category backfill complete: {total_updated} total jobs normalized")
        return {"total_updated": total_updated}

    except Exception as e:
        db.rollback()
        logger.error(f"Category backfill failed: {e}")
        raise

    finally:
        db.close()


@celery_app.task(name="app.tasks.data_quality_tasks.backfill_job_states")
def backfill_job_states(deactivate_non_texas: bool = True):
    """
    One-time task to populate state field for existing jobs.

    Parses state from location strings and optionally deactivates non-Texas jobs.
    Processes in batches to avoid memory issues.

    Args:
        deactivate_non_texas: If True, mark non-TX jobs as inactive
    """
    db = SyncSessionLocal()
    total_processed = 0
    total_texas = 0
    total_deactivated = 0
    batch_size = 1000

    try:
        while True:
            # Find jobs without state field
            jobs = db.query(JobPosting).filter(
                JobPosting.state.is_(None),
            ).limit(batch_size).all()

            if not jobs:
                break

            for job in jobs:
                state = parse_state_from_location(job.location)

                # If we can't parse state, default to TX for Texas-based orgs
                if state is None:
                    state = "TX"

                job.state = state
                total_processed += 1

                if state == "TX":
                    total_texas += 1
                elif deactivate_non_texas:
                    job.is_active = False
                    total_deactivated += 1

            db.commit()
            logger.info(
                f"State backfill progress: {total_processed} processed, "
                f"{total_texas} TX, {total_deactivated} deactivated"
            )

        logger.info(
            f"State backfill complete: {total_processed} total, "
            f"{total_texas} Texas, {total_deactivated} deactivated"
        )
        return {
            "total_processed": total_processed,
            "texas_jobs": total_texas,
            "deactivated": total_deactivated,
        }

    except Exception as e:
        db.rollback()
        logger.error(f"State backfill failed: {e}")
        raise

    finally:
        db.close()


@celery_app.task(name="app.tasks.data_quality_tasks.identify_non_texas_jobs")
def identify_non_texas_jobs():
    """
    Report on jobs that appear to be from non-Texas locations.

    Useful for auditing before running deactivation.
    """
    db = SyncSessionLocal()

    try:
        # Find active jobs with non-TX state
        non_tx = db.query(JobPosting).filter(
            JobPosting.is_active == True,  # noqa: E712
            JobPosting.state.isnot(None),
            JobPosting.state != "TX",
        ).all()

        # Group by state
        by_state: dict[str, list[dict]] = {}
        for job in non_tx:
            state = job.state or "unknown"
            if state not in by_state:
                by_state[state] = []
            by_state[state].append({
                "id": str(job.id),
                "title": job.title,
                "location": job.location,
                "platform": job.platform,
            })

        logger.info(f"Found {len(non_tx)} non-Texas jobs across {len(by_state)} states")

        return {
            "total": len(non_tx),
            "by_state": {state: len(jobs) for state, jobs in by_state.items()},
            "samples": {
                state: jobs[:3] for state, jobs in by_state.items()
            },
        }

    finally:
        db.close()


@celery_app.task(name="app.tasks.data_quality_tasks.backfill_job_cities")
def backfill_job_cities(batch_size: int = 500):
    """
    Derive city for job postings that don't have one.

    Uses the city resolver service to parse from location or inherit from org.
    Runs periodically to process newly scraped jobs.
    """
    db = SyncSessionLocal()
    try:
        # Find active jobs without city
        jobs = db.query(JobPosting).filter(
            JobPosting.city.is_(None),
            JobPosting.is_active == True,  # noqa: E712
        ).limit(batch_size).all()

        if not jobs:
            logger.info("No jobs need city backfill")
            return {"processed": 0, "updated": 0}

        updated = 0
        for job in jobs:
            # Get the organization for this job
            org = db.query(Organization).filter(
                Organization.id == job.organization_id
            ).first()

            city = resolve_city_for_job(job, org)
            if city:
                job.city = city
                updated += 1

        db.commit()
        logger.info(f"Backfilled city for {updated} jobs")
        return {"processed": len(jobs), "updated": updated}

    except Exception as e:
        db.rollback()
        logger.error(f"City backfill failed: {e}")
        raise

    finally:
        db.close()


@celery_app.task(name="app.tasks.data_quality_tasks.derive_org_cities")
def derive_org_cities(batch_size: int = 500):
    """
    Derive city for organizations that don't have one.

    Uses county seat lookup for Texas organizations.
    """
    db = SyncSessionLocal()
    try:
        # Find orgs without city but with county (for county seat lookup)
        orgs = db.query(Organization).filter(
            Organization.city.is_(None),
            Organization.county.isnot(None),
        ).limit(batch_size).all()

        if not orgs:
            logger.info("No organizations need city derivation")
            return {"processed": 0, "updated": 0}

        updated = 0
        for org in orgs:
            city, source = derive_org_city(org)
            if city:
                org.city = city
                org.city_source = source
                updated += 1

        db.commit()
        logger.info(f"Derived city for {updated} organizations")
        return {"processed": len(orgs), "updated": updated}

    except Exception as e:
        db.rollback()
        logger.error(f"Org city derivation failed: {e}")
        raise

    finally:
        db.close()
