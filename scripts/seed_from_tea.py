"""Seed organizations table from TEA district database.

Imports all 1,218 Texas districts (ISDs + charters) from the TEA data SQLite DB
into the PostgreSQL organizations table.

Usage:
    docker compose exec backend python -m scripts.seed_from_tea
    # Or from host with TEA DB path override:
    TEA_DB_PATH=/path/to/tea_data.db python scripts/seed_from_tea.py
"""

import re
import sqlite3
import sys
import uuid

from app.config import get_settings
from app.models.base import SyncSessionLocal
from app.models.organization import Organization
from app.models.scrape_source import ScrapeSource  # noqa: F401 — needed for relationship resolution
from app.models.job_posting import JobPosting  # noqa: F401
from app.models.scrape_run import ScrapeRun  # noqa: F401

settings = get_settings()


def make_slug(name: str) -> str:
    """Generate URL-safe slug from district name.

    Examples:
        'HUMBLE ISD' -> 'humble-isd'
        'A+ ACADEMY' -> 'a-plus-academy'
        'YES PREP PUBLIC SCHOOLS INC' -> 'yes-prep-public-schools-inc'
    """
    slug = name.lower().strip()
    slug = slug.replace("+", "-plus")
    slug = slug.replace("&", "-and-")
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    slug = slug.strip("-")
    return slug


def map_org_type(district_type: str, charter_status: str) -> str:
    """Map TEA district_type/charter_status to our org_type."""
    if charter_status and "CHARTER" in charter_status.upper():
        return "charter"
    if district_type and district_type.upper() == "ISD":
        return "isd"
    return "isd"


def seed():
    tea_db_path = settings.tea_db_path
    print(f"Reading districts from {tea_db_path}...")

    conn = sqlite3.connect(tea_db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.execute(
        "SELECT tea_id, name, region, county, district_type, charter_status, total_students FROM districts"
    )
    rows = cursor.fetchall()
    conn.close()

    print(f"Found {len(rows)} districts in TEA database")

    db = SyncSessionLocal()
    try:
        created = 0
        skipped = 0
        used_slugs = set()  # Track slugs assigned in this batch

        # Pre-load existing slugs from DB
        existing_slugs = {row[0] for row in db.query(Organization.slug).all()}
        used_slugs.update(existing_slugs)

        for row in rows:
            tea_id = row["tea_id"]

            # Check if already exists
            existing = db.query(Organization).filter(Organization.tea_id == tea_id).first()
            if existing:
                skipped += 1
                continue

            slug = make_slug(row["name"])

            # Handle slug collisions (check both DB and in-flight batch)
            base_slug = slug
            counter = 2
            while slug in used_slugs:
                slug = f"{base_slug}-{counter}"
                counter += 1
            used_slugs.add(slug)

            org = Organization(
                id=uuid.uuid4(),
                tea_id=tea_id,
                name=row["name"],
                slug=slug,
                org_type=map_org_type(row["district_type"], row["charter_status"]),
                esc_region=row["region"],
                county=row["county"],
                state="TX",
                total_students=row["total_students"],
                district_type=row["district_type"],
                charter_status=row["charter_status"],
                platform_status="unmapped",
            )
            db.add(org)
            created += 1

            if created % 100 == 0:
                db.flush()
                print(f"  ...{created} created so far")

        db.commit()
        print(f"\nDone: {created} created, {skipped} skipped (already exist)")
        print(f"Total organizations: {db.query(Organization).count()}")

    except Exception as e:
        db.rollback()
        print(f"Error: {e}", file=sys.stderr)
        raise
    finally:
        db.close()


if __name__ == "__main__":
    seed()
