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

# Full state names → abbreviation. Used when locations like "Tampa, Florida"
# don't end in a 2-letter abbreviation. Multi-word names (e.g. "WEST VIRGINIA")
# must be matched before single-word substrings of them ("VIRGINIA"), which
# _parse_state handles by sorting by length descending.
STATE_NAMES = {
    "ALABAMA": "AL", "ALASKA": "AK", "ARIZONA": "AZ", "ARKANSAS": "AR",
    "CALIFORNIA": "CA", "COLORADO": "CO", "CONNECTICUT": "CT", "DELAWARE": "DE",
    "FLORIDA": "FL", "GEORGIA": "GA", "HAWAII": "HI", "IDAHO": "ID",
    "ILLINOIS": "IL", "INDIANA": "IN", "IOWA": "IA", "KANSAS": "KS",
    "KENTUCKY": "KY", "LOUISIANA": "LA", "MAINE": "ME", "MARYLAND": "MD",
    "MASSACHUSETTS": "MA", "MICHIGAN": "MI", "MINNESOTA": "MN", "MISSISSIPPI": "MS",
    "MISSOURI": "MO", "MONTANA": "MT", "NEBRASKA": "NE", "NEVADA": "NV",
    "NEW HAMPSHIRE": "NH", "NEW JERSEY": "NJ", "NEW MEXICO": "NM", "NEW YORK": "NY",
    "NORTH CAROLINA": "NC", "NORTH DAKOTA": "ND", "OHIO": "OH", "OKLAHOMA": "OK",
    "OREGON": "OR", "PENNSYLVANIA": "PA", "RHODE ISLAND": "RI",
    "SOUTH CAROLINA": "SC", "SOUTH DAKOTA": "SD", "TENNESSEE": "TN", "TEXAS": "TX",
    "UTAH": "UT", "VERMONT": "VT", "VIRGINIA": "VA", "WASHINGTON": "WA",
    "WEST VIRGINIA": "WV", "WISCONSIN": "WI", "WYOMING": "WY",
    "DISTRICT OF COLUMBIA": "DC",
}
_STATE_NAMES_BY_LENGTH = sorted(STATE_NAMES, key=len, reverse=True)


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
            # wait_until="networkidle" never settles on jobvite — background
            # trackers keep firing past the 30s default timeout. Use
            # domcontentloaded + explicit wait_for_selector for the job listing.
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            except Exception as e:
                logger.warning(f"goto raised {type(e).__name__}: {e} — continuing with whatever rendered")
            try:
                await page.wait_for_selector(
                    ".jv-job-list-name, .jv-featured-job", timeout=15000
                )
            except Exception:
                pass  # selector wait timed out — proceed anyway, listings may be found
            await human_delay(1500, 2500)

            jobs = []
            # Jobvite's current DOM (verified 2026-04-30):
            #   - Standard list: <tr> containing <td class="jv-job-list-name"><a>...</a></td>
            #     and a sibling <td class="jv-job-list-location">
            #   - Featured jobs:  <div class="jv-featured-job"> with .jv-featured-job-title a
            #     and .jv-featured-job-location
            # Old selectors (.jv-job-list__item, .jv-job-item, tr[data-job-id]) no longer match.
            listings = await page.query_selector_all(
                "tr:has(td.jv-job-list-name), .jv-featured-job"
            )

            if not listings:
                listings = await page.query_selector_all("[class*='job'], .posting")

            for listing in listings:
                try:
                    title_el = await listing.query_selector(
                        ".jv-job-list-name a, .jv-featured-job-title a, "
                        ".jv-job-list__title, h3, a"
                    )
                    if not title_el:
                        continue

                    title = await title_el.inner_text()
                    href = await title_el.get_attribute("href")

                    location_el = await listing.query_selector(
                        ".jv-job-list-location, .jv-featured-job-location, "
                        ".jv-job-list__location, .location"
                    )
                    location = await location_el.inner_text() if location_el else None

                    category_el = await listing.query_selector(
                        ".jv-job-list-category, .jv-featured-job-category, "
                        ".jv-job-list__category, .department, .category"
                    )
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
        """Parse state from location string like 'Houston, TX' or 'Tampa, Florida'."""
        if not location:
            return None
        text = location.strip().upper()
        # Check for 2-letter state at end: "Houston, TX" or "Houston TX"
        match = re.search(r"\b([A-Z]{2})\s*$", text)
        if match and match.group(1) in STATE_ABBREVS:
            return match.group(1)
        # Check for full state names. Longest-first so "WEST VIRGINIA" beats "VIRGINIA".
        for name in _STATE_NAMES_BY_LENGTH:
            if re.search(rf"\b{re.escape(name)}\b", text):
                return STATE_NAMES[name]
        return None

    def _is_texas_job(self, job: dict) -> bool:
        """Check if job is located in Texas. Strict: unparseable locations are rejected."""
        location = job.get("location")
        return self._parse_state(location) == "TX"

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
