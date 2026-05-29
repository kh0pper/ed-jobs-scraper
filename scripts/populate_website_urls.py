"""Populate organizations.website_url from NCES CCD directory data.

Reads the NCES Common Core of Data LEA directory CSV and matches Texas
districts to our organizations table by tea_id (ST_LEAID field).

Usage:
    docker compose exec backend python -m scripts.populate_website_urls
    docker compose exec backend python -m scripts.populate_website_urls --dry-run
"""

import argparse
import csv
import sys
from pathlib import Path

from app.models.base import SyncSessionLocal
from app.models.organization import Organization
from app.models.scrape_source import ScrapeSource  # noqa: F401
from app.models.job_posting import JobPosting  # noqa: F401
from app.models.scrape_run import ScrapeRun  # noqa: F401

NCES_CSV_PATH = Path("/app/data/nces_lea_2024_25.csv")


def load_nces_urls(csv_path: Path) -> dict[str, str]:
    """Load TX district website URLs from NCES CCD CSV, keyed by 6-digit tea_id."""
    urls: dict[str, str] = {}
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row.get("ST") != "TX":
                continue
            st_leaid = row.get("ST_LEAID", "").strip()
            website = row.get("WEBSITE", "").strip()
            if not st_leaid or not website or website in ("-1", "-2", "M", "N"):
                continue
            tea_id = st_leaid.removeprefix("TX-")
            if not website.startswith(("http://", "https://")):
                website = "http://" + website
            urls[tea_id] = website
    return urls


def main():
    parser = argparse.ArgumentParser(description="Populate website_url from NCES CCD")
    parser.add_argument("--dry-run", action="store_true", help="Print changes without committing")
    args = parser.parse_args()

    if not NCES_CSV_PATH.exists():
        print(f"ERROR: NCES CSV not found at {NCES_CSV_PATH}", file=sys.stderr)
        sys.exit(1)

    nces_urls = load_nces_urls(NCES_CSV_PATH)
    print(f"Loaded {len(nces_urls)} TX district URLs from NCES CCD")

    db = SyncSessionLocal()
    try:
        orgs = db.query(Organization).filter(
            Organization.tea_id.isnot(None),
            Organization.tea_id != "",
        ).all()

        updated = 0
        skipped_already = 0
        skipped_no_match = 0

        for org in orgs:
            nces_url = nces_urls.get(org.tea_id)
            if not nces_url:
                skipped_no_match += 1
                continue
            if org.website_url and org.website_url.strip():
                skipped_already += 1
                continue
            if args.dry_run:
                print(f"  WOULD SET {org.tea_id} {org.name:40s} → {nces_url}")
            else:
                org.website_url = nces_url
            updated += 1

        if not args.dry_run and updated > 0:
            db.commit()

        print(f"\nResults:")
        print(f"  Updated:          {updated}")
        print(f"  Already had URL:  {skipped_already}")
        print(f"  No NCES match:    {skipped_no_match}")
        print(f"  Total orgs:       {len(orgs)}")
        if args.dry_run:
            print("  (dry run — no changes committed)")
    finally:
        db.close()


if __name__ == "__main__":
    main()
