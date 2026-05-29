"""Crawl district websites to discover job posting platforms.

For each organization with a populated website_url and no active scrape
source, fetches the main site plus common career-page paths and classifies
outbound links by platform using the same classifier as scrape_esc_pages.

Usage:
    docker compose exec backend python -m scripts.discovery.crawl_district_websites --dry-run
    docker compose exec backend python -m scripts.discovery.crawl_district_websites
    docker compose exec backend python -m scripts.discovery.crawl_district_websites --resume --limit 100
"""

import argparse
import logging
import re
import time
import uuid
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from app.models.base import SyncSessionLocal
from app.models.organization import Organization
from app.models.scrape_source import ScrapeSource
from app.models.job_posting import JobPosting  # noqa: F401
from app.models.scrape_run import ScrapeRun  # noqa: F401
from scripts.discovery.scrape_esc_pages import classify_url

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

SUPPORTED_PLATFORMS = {
    "applitrack", "schoolspring", "eightfold", "taleo", "smartrecruiters",
    "jobvite", "ttcportals", "munis", "workday", "simple_career", "skyward",
    "frontline_erp", "skyward_vue",
}

CAREER_PATHS = [
    "",
    "/careers",
    "/jobs",
    "/employment",
    "/hr",
    "/human-resources",
    "/page/employment",
    "/page/careers",
    "/page/jobs",
    "/join-our-team",
    "/departments/human-resources",
]

APPLITRACK_BASE = "https://www.applitrack.com/{slug}/onlineapp/jobpostings/Output.asp?all=1"
SCHOOLSPRING_BASE = "https://{slug}.schoolspring.com/"

_CLIENT: httpx.Client | None = None


def _get_client() -> httpx.Client:
    global _CLIENT
    if _CLIENT is None:
        _CLIENT = httpx.Client(
            timeout=httpx.Timeout(connect=10, read=20, write=10, pool=10),
            follow_redirects=True,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/121.0.0.0 Safari/537.36",
            },
        )
    return _CLIENT


def _normalize_base_url(platform: str, slug: str, raw_url: str) -> str | None:
    """Build the canonical base_url for a discovered source."""
    if platform == "applitrack" and slug:
        return APPLITRACK_BASE.format(slug=slug)
    if platform == "schoolspring" and slug:
        return SCHOOLSPRING_BASE.format(slug=slug)
    if platform == "skyward":
        parsed = urlparse(raw_url)
        path = parsed.path
        if "rappljoblst484" not in path:
            path = re.sub(r'rappljoblst\d*\.w|rapplmnu\d*\.r', 'rappljoblst484.w', path)
        return f"{parsed.scheme}://{parsed.netloc}{path}"
    return raw_url


def crawl_org(org: Organization) -> list[dict]:
    """Crawl an org's website and return discovered platform links."""
    base = org.website_url.rstrip("/")
    if not base.startswith(("http://", "https://")):
        base = "http://" + base

    client = _get_client()
    discovered = {}

    for path in CAREER_PATHS:
        url = base + path
        try:
            resp = client.get(url)
            if resp.status_code >= 400:
                continue
        except (httpx.HTTPError, httpx.TimeoutException):
            continue

        final_url = str(resp.url)
        final_platform, final_slug = classify_url(final_url)
        if final_platform and final_platform not in discovered:
            discovered[final_platform] = {
                "platform": final_platform,
                "slug": final_slug,
                "url": final_url,
                "source": "redirect",
            }

        soup = BeautifulSoup(resp.text, "lxml")
        for a in soup.find_all("a", href=True):
            href = a["href"].strip()
            if not href or href.startswith(("#", "mailto:", "tel:", "javascript:")):
                continue
            full_url = urljoin(final_url, href)
            platform, slug = classify_url(full_url)
            if platform and platform not in discovered:
                link_text = a.get_text(strip=True)[:100]
                discovered[platform] = {
                    "platform": platform,
                    "slug": slug,
                    "url": full_url,
                    "source": f"link:{link_text}" if link_text else "link",
                }

        time.sleep(0.5)

    return list(discovered.values())


def main():
    parser = argparse.ArgumentParser(description="Crawl district websites for job platforms")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int, default=0, help="Max orgs to crawl (0=all)")
    parser.add_argument("--resume", action="store_true", help="Skip orgs already crawled this run")
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
                Organization.website_url.isnot(None),
                Organization.website_url != "",
                Organization.id.notin_(active_org_ids),
            )
            .order_by(Organization.total_students.desc().nullslast())
        )
        if args.limit:
            q = q.limit(args.limit)
        orgs = q.all()

        logger.info("Crawling %d orphan orgs with website_url", len(orgs))

        stats = {"crawled": 0, "hits": 0, "sources_created": 0, "errors": 0}
        platform_counts: dict[str, int] = {}

        for i, org in enumerate(orgs):
            if i > 0 and i % 50 == 0:
                logger.info("Progress: %d/%d crawled, %d hits, %d sources created",
                            i, len(orgs), stats["hits"], stats["sources_created"])

            try:
                links = crawl_org(org)
            except Exception as e:
                logger.warning("Error crawling %s (%s): %s", org.name, org.website_url, e)
                stats["errors"] += 1
                continue

            stats["crawled"] += 1

            for link in links:
                platform = link["platform"]
                slug = link["slug"]
                raw_url = link["url"]
                platform_counts[platform] = platform_counts.get(platform, 0) + 1

                if platform not in SUPPORTED_PLATFORMS:
                    continue

                existing = (
                    db.query(ScrapeSource)
                    .filter(
                        ScrapeSource.organization_id == org.id,
                        ScrapeSource.platform == platform,
                    )
                    .first()
                )
                if existing:
                    continue

                base_url = _normalize_base_url(platform, slug, raw_url)
                if not base_url:
                    continue

                stats["hits"] += 1

                if args.dry_run:
                    logger.info("  WOULD CREATE: %s | %s | %s | slug=%s",
                                org.name, platform, base_url[:80], slug)
                else:
                    source = ScrapeSource(
                        id=uuid.uuid4(),
                        organization_id=org.id,
                        platform=platform,
                        base_url=base_url,
                        slug=slug or org.slug,
                        is_active=True,
                        discovered_by="website_crawl",
                        scrape_frequency_minutes=360,
                    )
                    db.add(source)
                    db.commit()
                    stats["sources_created"] += 1
                    logger.info("  CREATED: %s | %s | %s", org.name, platform, base_url[:80])

            time.sleep(0.5)

        logger.info("Done. Stats: %s", stats)
        logger.info("Platform breakdown: %s", dict(sorted(platform_counts.items(), key=lambda x: -x[1])))
        if args.dry_run:
            logger.info("(dry run — no sources created)")

    finally:
        db.close()


if __name__ == "__main__":
    main()
