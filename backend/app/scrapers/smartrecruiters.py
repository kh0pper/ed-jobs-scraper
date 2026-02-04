"""SmartRecruiters scraper (e.g., KIPP Texas).

SmartRecruiters exposes a public JSON API.
"""

import logging

import httpx

from app.scrapers.base import BaseScraper
from app.scrapers.registry import register_scraper

logger = logging.getLogger(__name__)


@register_scraper("smartrecruiters")
class SmartRecruitersScraper(BaseScraper):

    def scrape(self) -> list[dict]:
        # SmartRecruiters API: https://api.smartrecruiters.com/v1/companies/{company}/postings
        # Extract company from URL like careers.smartrecruiters.com/KIPP/texas-ads
        base_url = self.source.base_url
        parts = base_url.rstrip("/").split("/")

        # Try to extract company ID from URL path
        company = None
        for i, part in enumerate(parts):
            if "smartrecruiters.com" in part and i + 1 < len(parts):
                company = parts[i + 1]
                break

        if not company:
            company = self.source.slug or "unknown"

        api_url = f"https://api.smartrecruiters.com/v1/companies/{company}/postings"
        all_jobs = []
        offset = 0
        limit = 100

        while True:
            logger.info(f"Fetching SmartRecruiters API offset={offset}")
            try:
                resp = httpx.get(
                    api_url,
                    params={"offset": offset, "limit": limit},
                    timeout=30,
                    headers={"Accept": "application/json"},
                )
                resp.raise_for_status()
                data = resp.json()
            except (httpx.HTTPError, ValueError) as e:
                logger.warning(f"SmartRecruiters API failed: {e}")
                break

            postings = data.get("content", [])
            if not postings:
                break

            all_jobs.extend(postings)
            offset += limit

            if len(postings) < limit:
                break

        logger.info(f"Fetched {len(all_jobs)} postings from SmartRecruiters")
        return all_jobs

    def normalize(self, raw: dict) -> dict:
        location = raw.get("location", {})
        city = location.get("city") if isinstance(location, dict) else None
        loc_str = f"{city}, {location.get('region', '')}" if city else None

        return {
            "title": raw.get("name", "Unknown Position"),
            "application_url": raw.get("ref", raw.get("applyUrl", self.source.base_url)),
            "location": loc_str,
            "city": city,
            "department": raw.get("department", {}).get("label") if isinstance(raw.get("department"), dict) else None,
            "employment_type": raw.get("typeOfEmployment", {}).get("label") if isinstance(raw.get("typeOfEmployment"), dict) else None,
            "external_id": raw.get("id"),
            "extra_data": {
                "experience": raw.get("experienceLevel", {}).get("label") if isinstance(raw.get("experienceLevel"), dict) else None,
            },
        }
