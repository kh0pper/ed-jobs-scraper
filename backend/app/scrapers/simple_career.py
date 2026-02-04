"""Simple career page scraper for generic HTML career/jobs pages.

Used for nonprofits, associations, and small orgs that have basic
HTML career pages without a third-party platform.
"""

import logging
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

from app.scrapers.base import BaseScraper
from app.scrapers.registry import register_scraper

logger = logging.getLogger(__name__)

# Keywords indicating a link is a job posting
JOB_KEYWORDS = {
    "apply", "position", "opening", "career", "job", "opportunity",
    "coordinator", "director", "manager", "specialist", "analyst",
    "teacher", "instructor", "associate", "assistant", "officer",
    "developer", "engineer", "administrator",
}


@register_scraper("simple_career")
class SimpleCareerScraper(BaseScraper):

    def scrape(self) -> list[dict]:
        url = self.source.base_url
        logger.info(f"Fetching career page: {url}")

        resp = httpx.get(
            url,
            timeout=30,
            follow_redirects=True,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/121.0.0.0 Safari/537.36",
            },
        )
        resp.raise_for_status()

        soup = BeautifulSoup(resp.text, "lxml")
        jobs = []

        # Strategy 1: Look for structured job listing elements
        for listing in soup.select(".job-listing, .career-listing, .position, .opening, [class*='job-item']"):
            title_el = listing.find(["h2", "h3", "h4", "a"])
            if title_el:
                title = title_el.get_text(strip=True)
                href = title_el.get("href") if title_el.name == "a" else None
                if not href:
                    link = listing.find("a")
                    href = link.get("href") if link else None

                if title and self._looks_like_job(title):
                    job_url = urljoin(url, href) if href else url
                    jobs.append({"title": title, "url": job_url})

        # Strategy 2: If no structured elements, look for links with job-like text
        if not jobs:
            for link in soup.find_all("a", href=True):
                text = link.get_text(strip=True)
                if text and len(text) > 10 and self._looks_like_job(text):
                    href = link["href"]
                    job_url = urljoin(url, href)
                    # Avoid navigation links
                    if any(skip in href.lower() for skip in ("#", "mailto:", "javascript:", "facebook.", "twitter.")):
                        continue
                    jobs.append({"title": text, "url": job_url})

        # Deduplicate by URL
        seen = set()
        unique_jobs = []
        for job in jobs:
            if job["url"] not in seen:
                seen.add(job["url"])
                unique_jobs.append(job)

        logger.info(f"Found {len(unique_jobs)} job-like links on career page")
        return unique_jobs

    def normalize(self, raw: dict) -> dict:
        return {
            "title": raw["title"],
            "application_url": raw["url"],
        }

    @staticmethod
    def _looks_like_job(text: str) -> bool:
        """Heuristic: does this text look like a job title?"""
        words = set(text.lower().split())
        return bool(words & JOB_KEYWORDS)
