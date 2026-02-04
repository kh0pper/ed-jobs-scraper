"""Applitrack/Frontline scraper.

Handles all districts using the Applitrack platform.
URL pattern: https://www.applitrack.com/{slug}/onlineapp/default.aspx?all=1

The page loads a table with id="listy" containing job listings.
Columns: Title | Location | Date Posted
"""

import logging
from datetime import datetime

import httpx
from bs4 import BeautifulSoup

from app.scrapers.base import BaseScraper
from app.scrapers.registry import register_scraper

logger = logging.getLogger(__name__)

APPLITRACK_BASE = "https://www.applitrack.com"


@register_scraper("applitrack")
class ApplitrackScraper(BaseScraper):

    def scrape(self) -> list[dict]:
        url = self.source.base_url
        if not url:
            slug = self.source.slug
            url = f"{APPLITRACK_BASE}/{slug}/onlineapp/default.aspx?all=1"

        logger.info(f"Fetching Applitrack page: {url}")

        response = httpx.get(
            url,
            timeout=60,
            follow_redirects=True,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
            },
        )
        response.raise_for_status()

        soup = BeautifulSoup(response.text, "lxml")
        job_table = soup.find("table", id="listy")

        if not job_table:
            logger.warning(f"No job table found at {url}")
            return []

        jobs = []
        for row in job_table.find_all("tr")[1:]:  # Skip header
            cols = row.find_all("td")
            if len(cols) < 3:
                continue

            title = cols[0].get_text(strip=True)
            location = cols[1].get_text(strip=True)
            date_str = cols[2].get_text(strip=True)

            # Parse job URL
            link_tag = cols[0].find("a")
            if link_tag and link_tag.get("href"):
                href = link_tag["href"]
                if href.startswith("/"):
                    job_url = f"{APPLITRACK_BASE}/{self.source.slug}/onlineapp/{href.lstrip('/')}"
                elif href.startswith("http"):
                    job_url = href
                else:
                    job_url = f"{APPLITRACK_BASE}/{self.source.slug}/onlineapp/{href}"
            else:
                job_url = url

            jobs.append({
                "title": title,
                "location": location,
                "date_str": date_str,
                "url": job_url,
            })

        logger.info(f"Parsed {len(jobs)} listings from Applitrack")
        return jobs

    def normalize(self, raw: dict) -> dict:
        posting_date = None
        if raw.get("date_str"):
            try:
                posting_date = datetime.strptime(raw["date_str"], "%m/%d/%Y")
            except ValueError:
                pass

        return {
            "title": raw["title"],
            "application_url": raw["url"],
            "location": raw.get("location"),
            "city": self._extract_city(raw.get("location", "")),
            "raw_category": raw.get("location"),
            "posting_date": posting_date,
        }

    @staticmethod
    def _extract_city(location: str) -> str | None:
        """Try to extract city from location string."""
        if not location:
            return None
        # Applitrack locations are often school names, not cities
        # Return as-is for now; normalization service will refine later
        return location.strip() or None
