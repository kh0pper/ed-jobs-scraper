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
        import time

        url = self.source.base_url
        logger.info(f"Fetching Munis page: {url}")

        # Munis 7-day failure breakdown (verified 2026-04-30): 7x read-timeout,
        # 3x DNS resolution failure (the latter coincided with crow's WiFi-only
        # freeze on 2026-04-27). All transient, no structural cause.
        # Retry with exponential backoff: 5s, 15s, 45s.
        resp = None
        for attempt in range(3):
            try:
                resp = httpx.get(
                    url,
                    timeout=30,
                    follow_redirects=True,
                    headers={
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/121.0.0.0 Safari/537.36",
                    },
                )
                resp.raise_for_status()
                break
            except (httpx.TimeoutException, httpx.HTTPError, httpx.NetworkError) as e:
                if attempt == 2:
                    raise
                wait = 5 * (3 ** attempt)
                logger.warning(f"Munis fetch attempt {attempt + 1}/3 failed ({type(e).__name__}: {e}); retrying in {wait}s")
                time.sleep(wait)
        assert resp is not None

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
