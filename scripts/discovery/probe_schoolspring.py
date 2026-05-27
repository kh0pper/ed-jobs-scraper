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
from app.models.job_posting import JobPosting  # noqa: F401
from app.models.scrape_run import ScrapeRun  # noqa: F401
from scripts.discovery._disambiguation import distinctive_token

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

    # Bare-acronym variants — production tenants sometimes use just the
    # first letter of a single-word base + "isd" (ALIEF ISD -> aisd uses
    # aisd.schoolspring.com, verified 2026-05-26), the multi-word
    # acronym + "isd" (FORT WORTH ISD -> fwisd), or hyphen-aware
    # acronyms (CYPRESS-FAIRBANKS ISD -> cfisd uses cfisd.schoolspring.com,
    # verified 2026-05-26). Without these, real tenants stay invisible
    # to the probe.
    words = re.split(r"[\s-]+", base)
    if "ISD" in name:
        if len(words) == 1 and words[0]:
            short = words[0][0].lower() + "isd"
            if short not in slugs:
                slugs.append(short)
        elif len(words) >= 2:
            acronym = "".join(w[0].lower() for w in words if w) + "isd"
            if len(acronym) >= 4 and acronym not in slugs:
                slugs.append(acronym)

    return slugs


def check_schoolspring_slug(slug: str, org_name: str, client: httpx.Client) -> bool:
    """Check if a SchoolSpring tenant has scrapeable jobs that look like
    they belong to *this* org.

    Previously probed the HTML root and matched 'job' or 'position' anywhere
    in the body — but SchoolSpring is a SPA that serves an identical shell
    for every subdomain, so that signal matched the global landing page for
    every guess. Result: 1,117 sources created, 936 of which produced zero
    jobs and were mass-deactivated on 2026-05-01.

    The current implementation hits the production JSON API
    (api.schoolspring.com/api/Jobs/GetPagedJobsWithSearch) and then
    requires that ownership of the returned tenant looks plausible:

    1. jobsList must be non-empty (rules out unregistered domains).
    2. EITHER the slug embeds the org's distinctive name token
       (e.g., 'humbleisd' contains 'humble' — a long-form match), OR at
       least one job in the response mentions that token in its employer,
       title, or location field.

    The second clause is what blocks the bare-acronym collision problem
    (29 orgs all claiming 'aisd' because their slug-generators emit the
    same fallback). Only the actual owner's tenant will surface the org's
    name in employer / title / location text.
    """
    api_url = (
        f"https://api.schoolspring.com/api/Jobs/GetPagedJobsWithSearch"
        f"?domainName={slug}.schoolspring.com&page=1&size=50"
    )
    try:
        resp = client.get(api_url, timeout=15)
        if resp.status_code != 200:
            return False
        payload = resp.json()
        jobs_list = ((payload or {}).get("value") or {}).get("jobsList") or []
        if not jobs_list:
            return False

        token = distinctive_token(org_name)
        if not token:
            # No verifiable token (very short / generic name) — refuse
            # to claim the tenant.
            return False
        if token in slug.lower():
            # Strong-slug shortcut: the slug itself encodes the org name
            # (e.g., 'humbleisd' for HUMBLE ISD). Accept without
            # content verification.
            return True
        # Weak-slug branch: bare-acronym or otherwise non-encoded slug.
        # Require the API to surface the token in any narrative field.
        for j in jobs_list:
            blob = (
                (j.get("employer") or "")
                + " "
                + (j.get("title") or "")
                + " "
                + (j.get("location") or "")
            ).lower()
            if token in blob:
                return True
        return False
    except (httpx.HTTPError, httpx.TimeoutException, ValueError):
        # ValueError covers JSONDecodeError from response.json()
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

                if check_schoolspring_slug(slug, org.name, client):
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
                        elif not existing.is_active:
                            # Reactivate a previously-deactivated source we
                            # have now rediscovered. Update slug/base_url
                            # in case the working slug differs from the
                            # historic one.
                            existing.is_active = True
                            existing.slug = slug
                            existing.base_url = url
                            existing.consecutive_failures = 0
                            org.platform_status = "mapped"
                            db.commit()
                            logger.info(f"  REACTIVATED: {org.name}")

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
