"""Multi-platform probe targeting only organizations with NO active source.

Runs the corrected Applitrack probe helpers (broadened signal +
bare-acronym slugs + tenant-ownership disambiguation) plus a new Munis
legacy-pattern probe against the ~719 orphaned ISDs/charters.

Usage:
    docker compose exec backend python -m scripts.discovery.re_probe_orphaned --dry-run
    docker compose exec backend python -m scripts.discovery.re_probe_orphaned
    docker compose exec backend python -m scripts.discovery.re_probe_orphaned --resume
    docker compose exec backend python -m scripts.discovery.re_probe_orphaned --platform munis
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
from app.models.job_posting import JobPosting  # noqa: F401
from app.models.scrape_run import ScrapeRun  # noqa: F401
from scripts.discovery.probe_applitrack import (
    generate_slugs as applitrack_slugs,
    check_applitrack_slug,
    APPLITRACK_BASE,
)
from scripts.discovery._disambiguation import distinctive_token

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

RATE_LIMIT_SECONDS = 1.0
ALL_PLATFORMS = ("applitrack", "munis")


# ---------------------------------------------------------------------------
# Munis legacy probe: {slug}.munisselfservice.com
# ---------------------------------------------------------------------------

def _munis_slugs(name: str) -> list[str]:
    """Generate candidate slugs for the munisselfservice.com pattern.

    The only confirmed convention is Harmony's
    `harmonypublicschoolstxemployees.munisselfservice.com` — i.e.,
    <base-no-spaces> + 'txemployees'. Also try <base>employees, <base>tx,
    and plain <base>.
    """
    name = name.strip().upper()
    base = name
    for suffix in (" ISD", " CISD", " CONSOLIDATED ISD", " INDEPENDENT SCHOOL DISTRICT",
                    " PUBLIC SCHOOLS", " ACADEMY", " CHARTER SCHOOL", " INC"):
        if base.endswith(suffix):
            base = base[: -len(suffix)].strip()
            break

    core = re.sub(r"[^a-z0-9]", "", base.lower())
    if not core:
        return []

    slugs = []
    for variant in (core + "txemployees", core + "employees", core + "tx", core):
        if variant not in slugs:
            slugs.append(variant)
    return slugs


def check_munis_slug(slug: str, org_name: str, client: httpx.Client) -> bool:
    """Check if a munisselfservice.com tenant exists and belongs to this org."""
    url = f"https://{slug}.munisselfservice.com/employmentopportunities/default.aspx"
    try:
        resp = client.get(url, timeout=20, follow_redirects=True)
        if resp.status_code not in (200, 302):
            return False
        body = resp.text.lower()
        if "munis" not in body and "employmentopportunities" not in body:
            return False
        # Ownership check
        token = distinctive_token(org_name)
        if not token:
            return False
        if token in slug.lower():
            return True
        return token in body
    except (httpx.HTTPError, httpx.TimeoutException):
        return False


# ---------------------------------------------------------------------------
# Platform dispatch table
# ---------------------------------------------------------------------------

PLATFORM_PROBERS = {
    "applitrack": {
        "slug_fn": applitrack_slugs,
        "check_fn": check_applitrack_slug,
        "url_fn": lambda slug: f"{APPLITRACK_BASE}/{slug}/onlineapp/jobpostings/Output.asp?all=1",
    },
    "munis": {
        "slug_fn": _munis_slugs,
        "check_fn": check_munis_slug,
        "url_fn": lambda slug: f"https://{slug}.munisselfservice.com/employmentopportunities/default.aspx",
    },
}


# ---------------------------------------------------------------------------
# Main probe loop
# ---------------------------------------------------------------------------

def probe(dry_run: bool = False, resume: bool = False, platforms: list[str] | None = None):
    platforms = platforms or list(ALL_PLATFORMS)
    for p in platforms:
        if p not in PLATFORM_PROBERS:
            logger.error("Unknown platform: %s. Available: %s", p, list(PLATFORM_PROBERS.keys()))
            return

    db = SyncSessionLocal()
    client = httpx.Client(
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/121.0.0.0 Safari/537.36",
        },
    )

    try:
        # Orphan filter: orgs with no active source on ANY platform
        active_org_ids = db.query(ScrapeSource.organization_id).filter(
            ScrapeSource.is_active == True  # noqa: E712
        ).subquery()

        query = db.query(Organization).filter(
            Organization.org_type.in_(["isd", "charter"]),
            Organization.id.notin_(active_org_ids),
        )

        if resume:
            # Skip orgs that already got a source from a prior partial run
            # of this script (any platform in our set)
            already_probed = db.query(ScrapeSource.organization_id).filter(
                ScrapeSource.platform.in_(platforms),
                ScrapeSource.is_active == True,  # noqa: E712
            ).subquery()
            query = query.filter(Organization.id.notin_(already_probed))

        orgs = query.order_by(Organization.total_students.desc().nullslast()).all()
        logger.info("Probing %d orphaned orgs across platforms: %s", len(orgs), platforms)

        hits_by_platform: dict[str, int] = {p: 0 for p in platforms}
        total_misses = 0

        for i, org in enumerate(orgs):
            found = False

            for platform_name in platforms:
                prober = PLATFORM_PROBERS[platform_name]
                slugs = prober["slug_fn"](org.name)

                for slug in slugs:
                    time.sleep(RATE_LIMIT_SECONDS)

                    if prober["check_fn"](slug, org.name, client):
                        url = prober["url_fn"](slug)
                        logger.info("HIT: %s (%s) -> %s/%s", org.name, org.tea_id, platform_name, slug)

                        if not dry_run:
                            existing = db.query(ScrapeSource).filter(
                                ScrapeSource.organization_id == org.id,
                                ScrapeSource.platform == platform_name,
                            ).first()

                            if not existing:
                                source = ScrapeSource(
                                    id=uuid.uuid4(),
                                    organization_id=org.id,
                                    platform=platform_name,
                                    base_url=url,
                                    slug=slug,
                                    discovered_by=f"probe_{platform_name}",
                                )
                                db.add(source)
                                org.platform_status = "mapped"
                                db.commit()
                            elif not existing.is_active:
                                existing.is_active = True
                                existing.slug = slug
                                existing.base_url = url
                                existing.consecutive_failures = 0
                                org.platform_status = "mapped"
                                db.commit()
                                logger.info("  REACTIVATED: %s", org.name)

                        hits_by_platform[platform_name] += 1
                        found = True
                        break  # Found on this platform, don't try more slugs

                if found:
                    break  # Found on a platform, don't try remaining platforms

            if not found:
                total_misses += 1

            if (i + 1) % 50 == 0:
                logger.info(
                    "Progress: %d/%d (hits: %s, misses: %d)",
                    i + 1, len(orgs), hits_by_platform, total_misses,
                )

        logger.info("Done: hits=%s, misses=%d out of %d orphaned orgs", hits_by_platform, total_misses, len(orgs))
        if dry_run:
            logger.info("(Dry run — no changes saved)")

    finally:
        client.close()
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Multi-platform probe for orphaned orgs")
    parser.add_argument("--dry-run", action="store_true", help="Don't write to database")
    parser.add_argument("--resume", action="store_true", help="Skip already-probed orgs")
    parser.add_argument("--platform", type=str, help="Comma-separated platforms (default: all)")
    args = parser.parse_args()
    plats = args.platform.split(",") if args.platform else None
    probe(dry_run=args.dry_run, resume=args.resume, platforms=plats)
