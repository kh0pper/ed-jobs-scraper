"""SchoolSpring scraper.

URL pattern: https://{slug}.schoolspring.com/
SchoolSpring pages are JS-rendered, so we use the stealth browser.
"""

import asyncio
import logging
from datetime import datetime

from app.scrapers.base import BaseScraper
from app.scrapers.registry import register_scraper

logger = logging.getLogger(__name__)


@register_scraper("schoolspring")
class SchoolSpringScraper(BaseScraper):

    def scrape(self) -> list[dict]:
        return asyncio.get_event_loop().run_until_complete(self._scrape_async())

    async def _scrape_async(self) -> list[dict]:
        from app.scrapers.browser import get_browser, human_delay

        url = self.source.base_url
        logger.info(f"Fetching SchoolSpring page: {url}")

        async with get_browser() as browser:
            page = await browser.new_page()
            await page.goto(url, wait_until="networkidle")
            await human_delay(1000, 2000)

            # SchoolSpring renders job listings dynamically
            # Look for job listing elements
            jobs = []
            listings = await page.query_selector_all(".job-listing, .search-result, tr.job-row, .opportunity-row")

            if not listings:
                # Try broader selectors
                listings = await page.query_selector_all("[data-job-id], .posting-item, .result-item")

            for listing in listings:
                try:
                    title_el = await listing.query_selector("a, .title, .job-title, h3, h4")
                    title = await title_el.inner_text() if title_el else None
                    href = await title_el.get_attribute("href") if title_el else None

                    location_el = await listing.query_selector(".location, .school, .district")
                    location = await location_el.inner_text() if location_el else None

                    date_el = await listing.query_selector(".date, .posted-date, .deadline")
                    date_str = await date_el.inner_text() if date_el else None

                    if title:
                        job_url = href if href and href.startswith("http") else f"{url.rstrip('/')}/{href}" if href else url
                        jobs.append({
                            "title": title.strip(),
                            "location": location.strip() if location else None,
                            "date_str": date_str.strip() if date_str else None,
                            "url": job_url,
                        })
                except Exception as e:
                    logger.debug(f"Failed to parse listing: {e}")

            logger.info(f"Parsed {len(jobs)} listings from SchoolSpring")
            return jobs

    def normalize(self, raw: dict) -> dict:
        posting_date = None
        if raw.get("date_str"):
            for fmt in ("%m/%d/%Y", "%B %d, %Y", "%Y-%m-%d"):
                try:
                    posting_date = datetime.strptime(raw["date_str"], fmt)
                    break
                except ValueError:
                    continue

        return {
            "title": raw["title"],
            "application_url": raw["url"],
            "location": raw.get("location"),
            "posting_date": posting_date,
        }
