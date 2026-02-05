"""Scrape ESC region job pages to discover district career platforms.

Each of the 20 ESC regions in Texas maintains a job board or links page
that aggregates district job postings. This script visits those pages,
extracts links, and classifies them by platform.

Usage:
    docker compose exec backend python -m scripts.discovery.scrape_esc_pages
    docker compose exec backend python -m scripts.discovery.scrape_esc_pages --dry-run
"""

import argparse
import logging
import re
import uuid
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup

from app.models.base import SyncSessionLocal
from app.models.organization import Organization
from app.models.scrape_source import ScrapeSource
from app.models.job_posting import JobPosting  # noqa: F401
from app.models.scrape_run import ScrapeRun  # noqa: F401

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# Known ESC region job board URLs
# These may change over time — update as discovered
ESC_JOB_PAGES = {
    1: "https://www.esc1.net/Page/1426",
    2: "https://www.esc2.net/page/district-employment-opportunities",
    3: "https://www.esc3.net/page/employment",
    4: "https://www.esc4.net/districtjobs/",
    5: "https://www.esc5.net/page/employment-opportunities",
    6: "https://www.esc6.net/page/districtjobs",
    7: "https://www.esc7.net/page/Employment",
    8: "https://www.esc8.net/page/employment",
    9: "https://www.esc9.net/page/employment",
    10: "https://teacherjobnet.org/",
    11: "https://www.esc11.net/page/district-job-openings",
    12: "https://www.esc12.net/page/employment",
    13: "https://www.esc13.net/hr/employment-a-c/",
    14: "https://jobboard.esc14.net/",
    15: "https://www.esc15.net/page/employment",
    16: "https://www.esc16.net/page/Employment",
    17: "https://www.esc17.net/page/employment",
    18: "https://www.esc18.net/page/employment",
    19: "https://www.esc19.net/page/employment",
    20: "https://www.esc20.net/page/employment-opportunities",
}

# Platform detection patterns
PLATFORM_PATTERNS = [
    ("applitrack", re.compile(r"applitrack\.com/([^/]+)/", re.I)),
    ("schoolspring", re.compile(r"([^.]+)\.schoolspring\.com", re.I)),
    ("eightfold", re.compile(r"eightfold\.ai|apply\.[^/]+\.org/careers", re.I)),
    ("taleo", re.compile(r"taleo\.net", re.I)),
    ("smartrecruiters", re.compile(r"smartrecruiters\.com", re.I)),
    ("jobvite", re.compile(r"jobvite\.com", re.I)),
    ("workday", re.compile(r"myworkdayjobs\.com|wd\d\.myworkday", re.I)),
    ("munis", re.compile(r"munisselfservice\.com", re.I)),
    ("ttcportals", re.compile(r"ttcportals\.com", re.I)),
    ("peopleadmin", re.compile(r"peopleadmin\.com", re.I)),
    ("applicantpro", re.compile(r"applicantpro\.com", re.I)),
    ("teachermatch", re.compile(r"teachermatch\.org", re.I)),
]


def classify_url(url: str) -> tuple[str | None, str | None]:
    """Classify a URL by job posting platform.

    Returns (platform_name, slug_or_identifier) or (None, None).
    """
    for platform, pattern in PLATFORM_PATTERNS:
        match = pattern.search(url)
        if match:
            slug = match.group(1) if match.lastindex else None
            return platform, slug
    return None, None


def normalize_district_name(name: str) -> str:
    """Normalize a district name for fuzzy matching."""
    name = name.upper().strip()
    # Remove common noise
    for noise in ("INDEPENDENT SCHOOL DISTRICT", "ISD", "CISD", "CONSOLIDATED",
                  "PUBLIC SCHOOLS", "CHARTER", "ACADEMY", "INC", "OF TEXAS"):
        name = name.replace(noise, "")
    name = re.sub(r"[^A-Z0-9]", "", name)
    return name


def match_to_org(link_text: str, link_url: str, orgs_by_normalized: dict) -> Organization | None:
    """Try to match a link to an organization in the database."""
    # Try matching link text first
    normalized = normalize_district_name(link_text)
    if normalized and normalized in orgs_by_normalized:
        return orgs_by_normalized[normalized]

    # Try matching URL slug
    parsed = urlparse(link_url)
    path_parts = parsed.path.strip("/").split("/")
    for part in path_parts:
        normalized = normalize_district_name(part)
        if normalized and normalized in orgs_by_normalized:
            return orgs_by_normalized[normalized]

    return None


def scrape_esc_page(region: int, url: str, client: httpx.Client) -> list[dict]:
    """Scrape a single ESC page for job posting links.

    Returns list of dicts: {link_text, link_url, platform, slug}
    """
    logger.info(f"Scraping ESC Region {region}: {url}")
    try:
        resp = client.get(url, timeout=30, follow_redirects=True)
        resp.raise_for_status()
    except (httpx.HTTPError, httpx.TimeoutException) as e:
        logger.warning(f"Failed to fetch ESC {region}: {e}")
        return []

    soup = BeautifulSoup(resp.text, "lxml")
    results = []

    for link in soup.find_all("a", href=True):
        href = link["href"]
        text = link.get_text(strip=True)

        if not text or len(text) < 3:
            continue

        platform, slug = classify_url(href)
        if platform:
            results.append({
                "link_text": text,
                "link_url": href,
                "platform": platform,
                "slug": slug,
                "region": region,
            })

    logger.info(f"  ESC {region}: found {len(results)} platform links")
    return results


def scrape(dry_run: bool = False):
    db = SyncSessionLocal()
    client = httpx.Client(
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/121.0.0.0 Safari/537.36",
        },
    )

    try:
        # Build normalized name -> org lookup
        orgs = db.query(Organization).filter(
            Organization.org_type.in_(["isd", "charter"]),
        ).all()
        orgs_by_normalized = {}
        for org in orgs:
            key = normalize_district_name(org.name)
            if key:
                orgs_by_normalized[key] = org

        total_matched = 0
        total_links = 0
        total_new_sources = 0

        for region, url in sorted(ESC_JOB_PAGES.items()):
            links = scrape_esc_page(region, url, client)
            total_links += len(links)

            for link in links:
                org = match_to_org(link["link_text"], link["link_url"], orgs_by_normalized)
                if not org:
                    continue

                total_matched += 1

                if dry_run:
                    logger.info(f"  MATCH: {org.name} -> {link['platform']} ({link['link_url'][:80]})")
                    continue

                # Check if source already exists
                existing = db.query(ScrapeSource).filter(
                    ScrapeSource.organization_id == org.id,
                    ScrapeSource.platform == link["platform"],
                ).first()

                if not existing:
                    source = ScrapeSource(
                        id=uuid.uuid4(),
                        organization_id=org.id,
                        platform=link["platform"],
                        base_url=link["link_url"],
                        slug=link.get("slug"),
                        discovered_by="esc_scrape",
                    )
                    db.add(source)
                    org.platform_status = "mapped"
                    total_new_sources += 1

            db.commit()

        logger.info(f"\nSummary:")
        logger.info(f"  Total platform links found: {total_links}")
        logger.info(f"  Matched to organizations: {total_matched}")
        logger.info(f"  New sources created: {total_new_sources}")
        if dry_run:
            logger.info("  (Dry run — no changes saved)")

    finally:
        client.close()
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Scrape ESC region pages for district job platforms")
    parser.add_argument("--dry-run", action="store_true", help="Don't write to database")
    args = parser.parse_args()
    scrape(dry_run=args.dry_run)
