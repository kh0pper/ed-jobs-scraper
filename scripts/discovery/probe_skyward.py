"""Probe for ISCorp-hosted Skyward tenants among orphaned districts.

Many Texas districts host Skyward applicant tracking on the shared ISCorp
server at a predictable URL pattern:

    https://skyward.iscorp.com/scripts/wsisa.dll/WService=ws{fin|com}{name}tx/rappljoblst484.w

The generic website crawl misses these because it only checks district-domain
career paths, not the ISCorp shared host. This probe generates WService slug
candidates from each orphan's name and checks the ISCorp pattern.

Signal: HTTP 200 + `zD[` in body (the JavaScript job-array our Skyward scraper
parses). Invalid slugs return a ~300-byte stub with no zD entries.

Usage:
    docker compose exec backend python -m scripts.discovery.probe_skyward --dry-run
    docker compose exec backend python -m scripts.discovery.probe_skyward
    docker compose exec backend python -m scripts.discovery.probe_skyward --limit 100
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
ISCORP_BASE = "https://skyward.iscorp.com/scripts/wsisa.dll/WService={service}/rappljoblst484.w"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/121.0.0.0 Safari/537.36"


def generate_services(name: str) -> list[str]:
    """Generate candidate WService slug values from a district name.

    Observed patterns (from confirmed tenants):
        ANGLETON ISD            -> wsfinangletontx
        BELTON ISD              -> wsfinbeltonisdtx
        RED OAK ISD             -> wscomredoaktx        (wscom prefix!)
        GRAND PRAIRIE ISD       -> wsfingrandprairietx
        DUNCANVILLE ISD         -> wsfinduncanvilletx

    Middle = normalized district name; prefix is wsfin or wscom; suffix tx.
    We emit both prefixes, with and without an "isd" infix.
    """
    name = name.strip().upper()
    base = name
    for suffix in (" ISD", " CISD", " CONSOLIDATED ISD", " INDEPENDENT SCHOOL DISTRICT",
                   " PUBLIC SCHOOLS", " ACADEMY", " CHARTER SCHOOL", " INC"):
        if base.endswith(suffix):
            base = base[: -len(suffix)].strip()
            break

    base_compact = re.sub(r"[^a-z0-9]", "", base.lower())
    full_compact = re.sub(r"[^a-z0-9]", "", name.lower())  # retains ISD
    if not base_compact:
        return []

    middles = [base_compact]
    if full_compact != base_compact:
        middles.append(full_compact)  # e.g. beltonisd
    # First word only, for long multi-word names (littlecypress, grandprairie
    # are kept whole, but this helps names like "LITTLE CYPRESS-MAURICEVILLE")
    first_word = re.sub(r"[^a-z0-9]", "", re.split(r"[\s-]+", base)[0].lower())
    if first_word and first_word not in middles and len(first_word) >= 4:
        middles.append(first_word)

    services = []
    for mid in middles:
        for prefix in ("wsfin", "wscom"):
            svc = f"{prefix}{mid}tx"
            if svc not in services:
                services.append(svc)
    return services


def check_service(service: str, org_name: str, client: httpx.Client) -> str | None:
    """Probe one WService slug. Returns the working base_url or None.

    Verifies HTTP 200 + zD[ job array. Ownership-checks via distinctive_token
    when possible to avoid attributing a same-prefix tenant to the wrong org.
    """
    url = ISCORP_BASE.format(service=service)
    try:
        resp = client.get(url, timeout=20, follow_redirects=True,
                           headers={"User-Agent": USER_AGENT})
    except (httpx.HTTPError, httpx.TimeoutException):
        return None
    if resp.status_code != 200 or "zD[" not in resp.text:
        return None

    # Ownership check: the listing page repeats the district name in the
    # header. Require the distinctive token to appear (case-insensitive).
    token = distinctive_token(org_name)
    if token and token not in resp.text.lower():
        logger.info("  ownership mismatch for %s on %s (token %r absent)",
                    org_name, service, token)
        return None
    return url


def main():
    parser = argparse.ArgumentParser(description="Probe ISCorp Skyward tenants")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int, default=0, help="Max orgs to probe (0=all)")
    args = parser.parse_args()

    db = SyncSessionLocal()
    try:
        active_org_ids = (
            db.query(ScrapeSource.organization_id)
            .filter(ScrapeSource.is_active == True)  # noqa: E712
            .subquery()
        )
        q = (
            db.query(Organization)
            .filter(
                Organization.org_type.in_(["isd", "charter"]),
                Organization.id.notin_(active_org_ids),
            )
            .order_by(Organization.total_students.desc().nullslast())
        )
        if args.limit:
            q = q.limit(args.limit)
        orgs = q.all()
        logger.info("Probing %d orphan orgs for ISCorp Skyward", len(orgs))

        stats = {"probed": 0, "hits": 0, "created": 0}
        client = httpx.Client()
        try:
            for i, org in enumerate(orgs):
                if i > 0 and i % 50 == 0:
                    logger.info("Progress: %d/%d, %d hits", i, len(orgs), stats["hits"])
                stats["probed"] += 1
                hit_url = None
                for service in generate_services(org.name):
                    hit_url = check_service(service, org.name, client)
                    time.sleep(RATE_LIMIT_SECONDS)
                    if hit_url:
                        break
                if not hit_url:
                    continue
                stats["hits"] += 1
                if args.dry_run:
                    logger.info("  WOULD CREATE: %s | %s", org.name, hit_url)
                else:
                    db.add(ScrapeSource(
                        id=uuid.uuid4(),
                        organization_id=org.id,
                        platform="skyward",
                        base_url=hit_url,
                        slug=re.sub(r"[^a-z0-9]+", "-", org.name.lower()).strip("-"),
                        is_active=True,
                        discovered_by="probe_skyward",
                        scrape_frequency_minutes=360,
                    ))
                    db.commit()
                    stats["created"] += 1
                    logger.info("  CREATED: %s | %s", org.name, hit_url)
        finally:
            client.close()

        logger.info("Done. Stats: %s", stats)
        if args.dry_run:
            logger.info("(dry run — no sources created)")
    finally:
        db.close()


if __name__ == "__main__":
    main()
