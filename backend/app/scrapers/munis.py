"""Munis Self-Service scraper (e.g., Harmony Public Schools).

Munis renders a server-side HTML table, so httpx + BS4 works.
"""

import logging

import httpx
from bs4 import BeautifulSoup

from app.scrapers.base import BaseScraper
from app.scrapers.registry import register_scraper

logger = logging.getLogger(__name__)


@register_scraper("munis")
class MunisScraper(BaseScraper):

    def scrape(self) -> list[dict]:
        url = self.source.base_url
        logger.info(f"Fetching Munis page: {url}")

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

        # Munis uses a table or div-based listing
        rows = soup.select("table tr, .opportunity-row, .job-listing")

        for row in rows:
            cells = row.find_all("td")
            if not cells or len(cells) < 2:
                continue

            link = row.find("a")
            title = link.get_text(strip=True) if link else cells[0].get_text(strip=True)
            href = link.get("href") if link else None

            location = cells[1].get_text(strip=True) if len(cells) > 1 else None
            date_str = cells[2].get_text(strip=True) if len(cells) > 2 else None

            if title:
                if href and not href.startswith("http"):
                    # Resolve relative URL
                    from urllib.parse import urljoin
                    href = urljoin(url, href)

                jobs.append({
                    "title": title,
                    "location": location,
                    "date_str": date_str,
                    "url": href or url,
                })

        logger.info(f"Parsed {len(jobs)} listings from Munis")
        return jobs

    def normalize(self, raw: dict) -> dict:
        return {
            "title": raw["title"],
            "application_url": raw["url"],
            "location": raw.get("location"),
            "state": "TX",  # Munis sources are Texas school districts
        }
