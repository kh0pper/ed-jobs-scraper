"""Eightfold AI scraper (e.g., Houston ISD).

Eightfold exposes a JSON API for career listings.
"""

import logging
import re

import httpx

from app.scrapers.base import BaseScraper
from app.scrapers.registry import register_scraper

logger = logging.getLogger(__name__)


@register_scraper("eightfold")
class EightfoldScraper(BaseScraper):

    def scrape(self) -> list[dict]:
        """Eightfold has an API endpoint that returns JSON job data."""
        from urllib.parse import urlparse

        base_url = self.source.base_url.rstrip("/")
        parsed = urlparse(base_url)

        # Eightfold API is at domain root: /api/apply/v2/jobs
        # Note: Eightfold ignores num param and returns 10 per page
        api_url = f"{parsed.scheme}://{parsed.netloc}/api/apply/v2/jobs"
        page_size = 10

        all_jobs = []
        start = 0

        while True:
            params = {
                "num": page_size,
                "start": start,
                "domain": self.source.slug or "",
            }
            logger.info(f"Fetching Eightfold API start={start}: {api_url}")

            try:
                resp = httpx.get(
                    api_url,
                    params=params,
                    timeout=30,
                    headers={
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/121.0.0.0 Safari/537.36",
                        "Accept": "application/json",
                    },
                )
                resp.raise_for_status()
                data = resp.json()
            except (httpx.HTTPError, ValueError) as e:
                logger.warning(f"Eightfold API request failed: {e}")
                break

            positions = data.get("positions", [])
            if not positions:
                break

            all_jobs.extend(positions)
            start += len(positions)

            total = data.get("count", 0)
            if start >= total or len(positions) < page_size:
                break

        logger.info(f"Fetched {len(all_jobs)} positions from Eightfold")
        return all_jobs

    def normalize(self, raw: dict) -> dict:
        # Parse state from location (e.g., "Houston, TX" -> "TX")
        state = "TX"  # Default for Texas-based orgs
        location = raw.get("location", "")
        if location:
            match = re.search(r"\b([A-Z]{2})\b", location.upper())
            if match:
                state = match.group(1)

        return {
            "title": raw.get("name", "Unknown Position"),
            "application_url": raw.get("canonicalPositionUrl", raw.get("apply_url", self.source.base_url)),
            "location": location,
            "city": raw.get("city"),
            "state": state,
            "department": raw.get("department"),
            "employment_type": raw.get("type"),
            "description": raw.get("description", ""),
            "external_id": raw.get("id"),
            "extra_data": {
                "requisition_id": raw.get("requisitionId"),
                "team": raw.get("team"),
            },
        }
