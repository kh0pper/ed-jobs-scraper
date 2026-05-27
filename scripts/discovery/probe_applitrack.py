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
from app.models.job_posting import JobPosting  # noqa: F401
from app.models.scrape_run import ScrapeRun  # noqa: F401
from scripts.discovery._disambiguation import distinctive_token

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
    # (e.g., FORT WORTH ISD -> fwisd, CYPRESS-FAIRBANKS ISD -> cfisd).
    # Split on whitespace AND hyphens so hyphenated names like
    # CYPRESS-FAIRBANKS yield two words, not one.
    words = re.split(r"[\s-]+", base)
    if len(words) >= 2 and ("ISD" in name):
        acronym = "".join(w[0].lower() for w in words if w) + "isd"
        if len(acronym) >= 4 and acronym not in slugs:
            slugs.append(acronym)

    # Slug 7: bare-acronym variants — production slugs sometimes use just
    # the first letter of a single-word base + "isd" (PLANO ISD -> pisd,
    # ALIEF ISD -> aisd) or the bare acronym of a multi-word base without
    # the "isd" suffix (FORT WORTH ISD -> fw). The original Slug-6 branch
    # is gated on len(words)>=2 and always appended "isd", so neither
    # variant was reachable. Verified missing-slug cases as of 2026-05-26:
    # Plano uses applitrack.com/pisd/ (1.8 MB, 150 active jobs); Alief
    # uses aisd.schoolspring.com.
    if "ISD" in name:
        if len(words) == 1 and words[0]:
            short = words[0][0].lower() + "isd"
            if short not in slugs:
                slugs.append(short)
        elif len(words) >= 2:
            bare = "".join(w[0].lower() for w in words if w)
            if len(bare) >= 2 and bare not in slugs:
                slugs.append(bare)

    return slugs


def check_applitrack_slug(slug: str, org_name: str, client: httpx.Client) -> bool:
    """Check if an Applitrack tenant exists at this slug AND plausibly
    belongs to the org being probed.

    Structural signal: status 200 AND either `JobID:` (page has current
    openings) OR `VacanciesAreOnThisPage` (Applitrack-specific JS
    variable emitted on every listings page). The latter was added
    2026-05-26 after live verification showed Dallas/Frisco/Cy-Fair
    return Applitrack listing pages with `var VacanciesAreOnThisPage =
    true` but no `JobID:` markers when no current openings exist.

    Ownership signal: each applitrack URL slug maps to exactly one
    tenant, but multiple orgs can generate the same candidate slug —
    most painfully the bare-acronym fallbacks (`pisd`, `aisd`, ...) that
    are valid for any P-, A-, etc. district. We require EITHER the slug
    to embed the org's distinctive name token (strong slug — e.g.,
    'humbleisd' contains 'humble'), OR the body content to surface that
    token in a non-URL context (URL slugs naturally don't contain the
    token in the weak-slug branch, so URL strings can't false-positive).
    """
    url = f"{APPLITRACK_BASE}/{slug}/onlineapp/jobpostings/Output.asp?all=1"
    try:
        resp = client.get(url, timeout=15, follow_redirects=True)
        if resp.status_code != 200:
            return False
        body = resp.text
        if "JobID:" not in body and "VacanciesAreOnThisPage" not in body:
            return False

        token = distinctive_token(org_name)
        if not token:
            return False
        if token in slug.lower():
            return True
        return token in body.lower()
    except (httpx.HTTPError, httpx.TimeoutException):
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

                if check_applitrack_slug(slug, org.name, client):
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
    parser = argparse.ArgumentParser(description="Probe Applitrack for Texas district job pages")
    parser.add_argument("--dry-run", action="store_true", help="Don't write to database")
    parser.add_argument("--resume", action="store_true", help="Skip already-mapped orgs")
    args = parser.parse_args()
    probe(dry_run=args.dry_run, resume=args.resume)
