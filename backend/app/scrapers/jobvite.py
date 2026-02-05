"""Jobvite scraper (e.g., IDEA Public Schools).

Jobvite career pages are JS-rendered.
"""

import asyncio
import logging
import re

from app.scrapers.base import BaseScraper
from app.scrapers.registry import register_scraper

logger = logging.getLogger(__name__)

# State abbreviations for filtering
STATE_ABBREVS = {
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA", "HI", "ID", "IL", "IN", "IA",
    "KS", "KY", "LA", "ME", "MD", "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ",
    "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC", "SD", "TN", "TX", "UT", "VT",
    "VA", "WA", "WV", "WI", "WY", "DC",
}


@register_scraper("jobvite")
class JobviteScraper(BaseScraper):

    def scrape(self) -> list[dict]:
        return asyncio.get_event_loop().run_until_complete(self._scrape_async())

    async def _scrape_async(self) -> list[dict]:
        from app.scrapers.browser import get_browser, human_delay

        url = self.source.base_url
        logger.info(f"Fetching Jobvite page: {url}")

        async with get_browser() as browser:
            page = await browser.new_page()
            await page.goto(url, wait_until="networkidle")
            await human_delay(2000, 3000)

            jobs = []
            listings = await page.query_selector_all(".jv-job-list__item, .jv-job-item, tr[data-job-id]")

            if not listings:
                listings = await page.query_selector_all("[class*='job'], .posting")

            for listing in listings:
                try:
                    title_el = await listing.query_selector("a, .jv-job-list__title, h3")
                    if not title_el:
                        continue

                    title = await title_el.inner_text()
                    href = await title_el.get_attribute("href")

                    location_el = await listing.query_selector(".jv-job-list__location, .location")
                    location = await location_el.inner_text() if location_el else None

                    category_el = await listing.query_selector(".jv-job-list__category, .department, .category")
                    category = await category_el.inner_text() if category_el else None

                    if title and title.strip():
                        job_url = href if href and href.startswith("http") else f"https://jobs.jobvite.com{href}" if href else url
                        jobs.append({
                            "title": title.strip(),
                            "location": location.strip() if location else None,
                            "category": category.strip() if category else None,
                            "url": job_url,
                        })
                except Exception as e:
                    logger.debug(f"Failed to parse Jobvite listing: {e}")

            # Filter to Texas jobs only
            tx_jobs = [job for job in jobs if self._is_texas_job(job)]
            logger.info(f"Parsed {len(jobs)} total, {len(tx_jobs)} Texas listings from Jobvite")
            return tx_jobs

    def _parse_state(self, location: str | None) -> str | None:
        """Parse state from location string like 'Houston, TX' or 'Texas'."""
        if not location:
            return None
        text = location.strip().upper()
        # Check for 2-letter state at end: "Houston, TX" or "Houston TX"
        match = re.search(r"\b([A-Z]{2})\s*$", text)
        if match and match.group(1) in STATE_ABBREVS:
            return match.group(1)
        # Check for "Texas"
        if "TEXAS" in text:
            return "TX"
        return None

    def _is_texas_job(self, job: dict) -> bool:
        """Check if job is located in Texas."""
        location = job.get("location")
        state = self._parse_state(location)
        # Accept TX or unknown (for orgs we know are Texas-only)
        return state in ("TX", None)

    def normalize(self, raw: dict) -> dict:
        location = raw.get("location")
        state = self._parse_state(location)

        # Extract city from location (e.g., "Houston, TX" -> "Houston")
        city = None
        if location:
            parts = location.split(",")
            if parts:
                city = parts[0].strip()

        return {
            "title": raw["title"],
            "application_url": raw["url"],
            "location": location,
            "city": city,
            "state": state or "TX",  # Default to TX for known Texas orgs
            "raw_category": raw.get("category"),
        }
