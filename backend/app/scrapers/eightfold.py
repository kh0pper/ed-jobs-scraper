"""Eightfold AI scraper (e.g., Houston ISD).

Eightfold exposes a JSON API for career listings.
"""

import logging

import httpx

from app.scrapers.base import BaseScraper
from app.scrapers.registry import register_scraper

logger = logging.getLogger(__name__)


@register_scraper("eightfold")
class EightfoldScraper(BaseScraper):

    def scrape(self) -> list[dict]:
        """Eightfold has an API endpoint that returns JSON job data."""
        base_url = self.source.base_url.rstrip("/")

        # Eightfold API pattern: /api/apply/v2/jobs
        # The exact endpoint may vary per deployment
        api_url = f"{base_url}/api/apply/v2/jobs"
        params = {
            "num": 100,
            "start": 0,
            "domain": self.source.slug or "",
        }

        all_jobs = []
        page = 0

        while True:
            params["start"] = page * 100
            logger.info(f"Fetching Eightfold API page {page}: {api_url}")

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
            page += 1

            if len(positions) < 100:
                break

        logger.info(f"Fetched {len(all_jobs)} positions from Eightfold")
        return all_jobs

    def normalize(self, raw: dict) -> dict:
        return {
            "title": raw.get("name", "Unknown Position"),
            "application_url": raw.get("canonicalPositionUrl", raw.get("apply_url", self.source.base_url)),
            "location": raw.get("location", ""),
            "city": raw.get("city"),
            "department": raw.get("department"),
            "employment_type": raw.get("type"),
            "description": raw.get("description", ""),
            "external_id": raw.get("id"),
            "extra_data": {
                "requisition_id": raw.get("requisitionId"),
                "team": raw.get("team"),
            },
        }
