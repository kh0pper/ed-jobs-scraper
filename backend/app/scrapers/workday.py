"""Workday scraper (e.g., Teach For America).

Workday career sites expose a JSON API at /api/v1/plod/...
"""

import logging

import httpx

from app.scrapers.base import BaseScraper
from app.scrapers.registry import register_scraper

logger = logging.getLogger(__name__)


@register_scraper("workday")
class WorkdayScraper(BaseScraper):

    def scrape(self) -> list[dict]:
        """Workday has a JSON search API behind the career page."""
        base_url = self.source.base_url.rstrip("/")

        # Workday API endpoint pattern
        # Example: https://teachforamerica.wd1.myworkdayjobs.com/wday/cxs/teachforamerica/TFA_Careers/jobs
        parts = base_url.split("/")
        # Extract tenant and career site from URL
        # teachforamerica.wd1.myworkdayjobs.com -> tenant=teachforamerica, host=wd1
        host_parts = parts[2].split(".")
        tenant = host_parts[0]
        wd_host = ".".join(host_parts[1:])
        career_site = parts[-1] if len(parts) > 3 else "External"

        api_url = f"https://{tenant}.{wd_host}/wday/cxs/{tenant}/{career_site}/jobs"

        all_jobs = []
        offset = 0
        limit = 20

        while True:
            logger.info(f"Fetching Workday API offset={offset}")
            try:
                resp = httpx.post(
                    api_url,
                    json={"appliedFacets": {}, "limit": limit, "offset": offset, "searchText": ""},
                    timeout=30,
                    headers={
                        "Content-Type": "application/json",
                        "Accept": "application/json",
                    },
                )
                resp.raise_for_status()
                data = resp.json()
            except (httpx.HTTPError, ValueError) as e:
                logger.warning(f"Workday API failed: {e}")
                break

            postings = data.get("jobPostings", [])
            if not postings:
                break

            all_jobs.extend(postings)
            offset += limit

            total = data.get("total", 0)
            if offset >= total:
                break

        logger.info(f"Fetched {len(all_jobs)} postings from Workday")
        return all_jobs

    def normalize(self, raw: dict) -> dict:
        title = raw.get("title", "Unknown Position")
        external_path = raw.get("externalPath", "")
        base = self.source.base_url.rstrip("/")
        job_url = f"{base}{external_path}" if external_path else base

        location = raw.get("locationsText", "")
        posted_on = raw.get("postedOn", "")

        return {
            "title": title,
            "application_url": job_url,
            "location": location,
            "external_id": raw.get("bulletFields", [""])[0] if raw.get("bulletFields") else None,
            "extra_data": {
                "posted_on": posted_on,
            },
        }
