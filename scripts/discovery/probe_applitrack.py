"""Probe Applitrack for all Texas districts.

For each district in the organizations table, generates candidate URL slugs
and checks if they have an Applitrack job posting page.

Usage:
    docker compose exec backend python -m scripts.discovery.probe_applitrack
    # Dry run (no DB writes):
    docker compose exec backend python -m scripts.discovery.probe_applitrack --dry-run
    # Resume from where you left off:
    docker compose exec backend python -m scripts.discovery.probe_applitrack --resume
"""

import argparse
import logging
import re
import time
import uuid

import httpx

from app.models.base import SyncSessionLocal
from app.models.organization import Organization
from app.models.scrape_source import ScrapeSource

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

APPLITRACK_BASE = "https://www.applitrack.com"
RATE_LIMIT_SECONDS = 1.0


def generate_slugs(name: str) -> list[str]:
    """Generate candidate Applitrack slugs from a district name.

    Examples:
        'HUMBLE ISD' -> ['humbleisd', 'humble', 'humble-isd']
        'FORT WORTH ISD' -> ['fortworthisd', 'fortworth', 'fort-worth-isd', 'fwisd']
        'KIPP TEXAS PUBLIC SCHOOLS' -> ['kipptexas', 'kipptexaspublicschools']
        'A W BROWN LEADERSHIP ACADEMY' -> ['awbrownleadershipacademy', 'awbrown']
    """
    name = name.strip().upper()
    slugs = []

    # Remove common suffixes for base name
    base = name
    for suffix in (" ISD", " CISD", " CONSOLIDATED ISD", " INDEPENDENT SCHOOL DISTRICT",
                    " PUBLIC SCHOOLS", " ACADEMY", " CHARTER SCHOOL", " INC"):
        if base.endswith(suffix):
            base = base[: -len(suffix)].strip()
            break

    # Slug 1: base + "isd" (no spaces)
    if "ISD" in name or "INDEPENDENT" in name:
        s = re.sub(r"[^a-z0-9]", "", base.lower()) + "isd"
        slugs.append(s)

    # Slug 2: base only (no spaces)
    s = re.sub(r"[^a-z0-9]", "", base.lower())
    if s and s not in slugs:
        slugs.append(s)

    # Slug 3: full name (no spaces)
    s = re.sub(r"[^a-z0-9]", "", name.lower())
    if s and s not in slugs:
        slugs.append(s)

    # Slug 4: hyphenated base + isd
    if "ISD" in name or "INDEPENDENT" in name:
        s = re.sub(r"[^a-z0-9]+", "-", base.lower()).strip("-") + "-isd"
        if s not in slugs:
            slugs.append(s)

    # Slug 5: hyphenated full name
    s = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    if s and s not in slugs:
        slugs.append(s)

    # Slug 6: first-letter acronym + "isd" for multi-word names
    words = base.split()
    if len(words) >= 2 and ("ISD" in name):
        acronym = "".join(w[0].lower() for w in words if w) + "isd"
        if len(acronym) >= 4 and acronym not in slugs:
            slugs.append(acronym)

    return slugs


def check_applitrack_slug(slug: str, client: httpx.Client) -> bool:
    """Check if an Applitrack page exists for the given slug.

    Uses the Output.asp endpoint which returns all jobs.
    Returns True if the page returns 200 and contains job title tables.
    """
    url = f"{APPLITRACK_BASE}/{slug}/onlineapp/jobpostings/Output.asp?all=1"
    try:
        resp = client.get(url, timeout=15, follow_redirects=True)
        if resp.status_code == 200 and "JobID:" in resp.text:
            return True
    except (httpx.HTTPError, httpx.TimeoutException):
        pass
    return False


def probe(dry_run: bool = False, resume: bool = False):
    db = SyncSessionLocal()
    client = httpx.Client(
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/121.0.0.0 Safari/537.36",
        },
    )

    try:
        # Get all districts that haven't been mapped yet
        query = db.query(Organization).filter(
            Organization.org_type.in_(["isd", "charter"]),
        )

        if resume:
            # Skip orgs that already have an applitrack source
            mapped_org_ids = db.query(ScrapeSource.organization_id).filter(
                ScrapeSource.platform == "applitrack"
            ).subquery()
            query = query.filter(Organization.id.notin_(mapped_org_ids))
            query = query.filter(Organization.platform_status != "mapped")

        orgs = query.order_by(Organization.total_students.desc().nullslast()).all()
        logger.info(f"Probing Applitrack for {len(orgs)} organizations")

        hits = 0
        misses = 0

        for i, org in enumerate(orgs):
            slugs = generate_slugs(org.name)
            found = False

            for slug in slugs:
                time.sleep(RATE_LIMIT_SECONDS)

                if check_applitrack_slug(slug, client):
                    url = f"{APPLITRACK_BASE}/{slug}/onlineapp/jobpostings/Output.asp?all=1"
                    logger.info(f"HIT: {org.name} ({org.tea_id}) -> {slug}")

                    if not dry_run:
                        # Check if source already exists
                        existing = db.query(ScrapeSource).filter(
                            ScrapeSource.organization_id == org.id,
                            ScrapeSource.platform == "applitrack",
                        ).first()

                        if not existing:
                            source = ScrapeSource(
                                id=uuid.uuid4(),
                                organization_id=org.id,
                                platform="applitrack",
                                base_url=url,
                                slug=slug,
                                discovered_by="probe_applitrack",
                            )
                            db.add(source)
                            org.platform_status = "mapped"
                            db.commit()

                    hits += 1
                    found = True
                    break

            if not found:
                misses += 1

            if (i + 1) % 50 == 0:
                logger.info(f"Progress: {i + 1}/{len(orgs)} ({hits} hits, {misses} misses)")

        logger.info(f"Done: {hits} hits, {misses} misses out of {len(orgs)} orgs")
        if dry_run:
            logger.info("(Dry run — no changes saved)")

    finally:
        client.close()
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Probe Applitrack for Texas district job pages")
    parser.add_argument("--dry-run", action="store_true", help="Don't write to database")
    parser.add_argument("--resume", action="store_true", help="Skip already-mapped orgs")
    args = parser.parse_args()
    probe(dry_run=args.dry_run, resume=args.resume)
