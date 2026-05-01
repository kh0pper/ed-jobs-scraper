"""Workday scraper (e.g., Teach For America).

Workday career sites expose a JSON API at /api/v1/plod/...
"""

import logging

import httpx

from app.scrapers._states import parse_state
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

        # Filter to Texas jobs only
        tx_jobs = [job for job in all_jobs if self._is_texas_job(job)]
        logger.info(f"Fetched {len(all_jobs)} total, {len(tx_jobs)} Texas postings from Workday")
        return tx_jobs

    def _is_texas_job(self, job: dict) -> bool:
        """Check if job is located in Texas.

        Note: this is intentionally LOOSE — `state in ("TX", None)` accepts
        unparseable locations as TX. Workday tenants in this codebase are
        single-tenant TX-only orgs (e.g. Teach For America Texas) whose
        location strings are sometimes opaque ("Various locations", "Remote",
        free-form blurbs). Tightening this to strict TX-only would drop
        legitimate jobs. Do NOT apply jobvite's strict-mode pattern here
        without verifying the tenant set is actually multi-state.
        """
        state = parse_state(job.get("locationsText", ""))
        return state in ("TX", None)

    def normalize(self, raw: dict) -> dict:
        title = raw.get("title", "Unknown Position")
        external_path = raw.get("externalPath", "")
        base = self.source.base_url.rstrip("/")
        job_url = f"{base}{external_path}" if external_path else base

        location = raw.get("locationsText", "")
        posted_on = raw.get("postedOn", "")
        state = parse_state(location)

        # Extract city from location (e.g., "Houston, TX" -> "Houston")
        city = None
        if location:
            parts = location.split(",")
            if parts:
                city = parts[0].strip()

        return {
            "title": title,
            "application_url": job_url,
            "location": location,
            "city": city,
            "state": state or "TX",  # Default to TX for known Texas orgs
            "external_id": raw.get("bulletFields", [""])[0] if raw.get("bulletFields") else None,
            "extra_data": {
                "posted_on": posted_on,
            },
        }
