"""Probe SchoolSpring for all Texas districts.

Checks {slug}.schoolspring.com for each district.

Usage:
    docker compose exec backend python -m scripts.discovery.probe_schoolspring
    docker compose exec backend python -m scripts.discovery.probe_schoolspring --dry-run
    docker compose exec backend python -m scripts.discovery.probe_schoolspring --resume
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

RATE_LIMIT_SECONDS = 1.0


def generate_slugs(name: str) -> list[str]:
    """Generate candidate SchoolSpring slugs from a district name.

    SchoolSpring uses subdomain-based slugs: {slug}.schoolspring.com
    Common patterns: 'springisd', 'spring-isd', 'springindependentschooldistrict'
    """
    name = name.strip().upper()
    slugs = []

    # Remove common suffixes
    base = name
    for suffix in (" ISD", " CISD", " CONSOLIDATED ISD", " INDEPENDENT SCHOOL DISTRICT",
                    " PUBLIC SCHOOLS", " ACADEMY", " CHARTER SCHOOL", " INC"):
        if base.endswith(suffix):
            base = base[: -len(suffix)].strip()
            break

    # Slug: base + "isd" (no separators)
    if "ISD" in name:
        s = re.sub(r"[^a-z0-9]", "", base.lower()) + "isd"
        slugs.append(s)

    # Slug: base only
    s = re.sub(r"[^a-z0-9]", "", base.lower())
    if s and s not in slugs:
        slugs.append(s)

    # Slug: hyphenated base-isd
    if "ISD" in name:
        s = re.sub(r"[^a-z0-9]+", "-", base.lower()).strip("-") + "-isd"
        if s not in slugs:
            slugs.append(s)

    # Slug: full name no separators
    s = re.sub(r"[^a-z0-9]", "", name.lower())
    if s and s not in slugs:
        slugs.append(s)

    return slugs


def check_schoolspring_slug(slug: str, client: httpx.Client) -> bool:
    """Check if a SchoolSpring subdomain exists for the given slug."""
    url = f"https://{slug}.schoolspring.com/"
    try:
        resp = client.get(url, timeout=15, follow_redirects=True)
        # SchoolSpring returns 200 for valid districts with job content
        if resp.status_code == 200 and ("job" in resp.text.lower() or "position" in resp.text.lower()):
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
        query = db.query(Organization).filter(
            Organization.org_type.in_(["isd", "charter"]),
        )

        if resume:
            mapped_org_ids = db.query(ScrapeSource.organization_id).filter(
                ScrapeSource.platform == "schoolspring"
            ).subquery()
            query = query.filter(Organization.id.notin_(mapped_org_ids))
            # Only probe orgs not already mapped to another platform
            query = query.filter(Organization.platform_status.in_(["unmapped", "probing"]))

        orgs = query.order_by(Organization.total_students.desc().nullslast()).all()
        logger.info(f"Probing SchoolSpring for {len(orgs)} organizations")

        hits = 0
        misses = 0

        for i, org in enumerate(orgs):
            slugs = generate_slugs(org.name)
            found = False

            for slug in slugs:
                time.sleep(RATE_LIMIT_SECONDS)

                if check_schoolspring_slug(slug, client):
                    url = f"https://{slug}.schoolspring.com/"
                    logger.info(f"HIT: {org.name} ({org.tea_id}) -> {slug}")

                    if not dry_run:
                        existing = db.query(ScrapeSource).filter(
                            ScrapeSource.organization_id == org.id,
                            ScrapeSource.platform == "schoolspring",
                        ).first()

                        if not existing:
                            source = ScrapeSource(
                                id=uuid.uuid4(),
                                organization_id=org.id,
                                platform="schoolspring",
                                base_url=url,
                                slug=slug,
                                discovered_by="probe_schoolspring",
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
    parser = argparse.ArgumentParser(description="Probe SchoolSpring for Texas district job pages")
    parser.add_argument("--dry-run", action="store_true", help="Don't write to database")
    parser.add_argument("--resume", action="store_true", help="Skip already-mapped orgs")
    args = parser.parse_args()
    probe(dry_run=args.dry_run, resume=args.resume)
