"""Jobvite scraper (e.g., IDEA Public Schools).

Jobvite career pages are JS-rendered.
"""

import asyncio
import logging

from app.scrapers._states import parse_state
from app.scrapers.base import BaseScraper
from app.scrapers.registry import register_scraper

logger = logging.getLogger(__name__)


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

    def _is_texas_job(self, job: dict) -> bool:
        """Check if job is located in Texas. Strict: unparseable locations are rejected."""
        return parse_state(job.get("location")) == "TX"

    def normalize(self, raw: dict) -> dict:
        location = raw.get("location")
        state = parse_state(location)

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
