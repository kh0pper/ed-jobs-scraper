"""Taleo/CAPPS scraper (e.g., Texas Education Agency).

CAPPS (Centralized Accounting and Payroll/Personnel System) uses Oracle Taleo
for state agency job postings.
"""

import asyncio
import logging
from datetime import datetime

from app.scrapers.base import BaseScraper
from app.scrapers.registry import register_scraper

logger = logging.getLogger(__name__)


@register_scraper("taleo")
class TaleoScraper(BaseScraper):

    def scrape(self) -> list[dict]:
        return asyncio.get_event_loop().run_until_complete(self._scrape_async())

    async def _scrape_async(self) -> list[dict]:
        from app.scrapers.browser import get_browser, human_delay

        url = self.source.base_url
        logger.info(f"Fetching Taleo/CAPPS page: {url}")

        async with get_browser() as browser:
            page = await browser.new_page()
            await page.goto(url, wait_until="networkidle")
            await human_delay(2000, 4000)

            jobs = []

            # Taleo renders a job search results table
            rows = await page.query_selector_all("table.tablecontent tr, .requisitionListItem, .searchResultItem")

            for row in rows:
                try:
                    link_el = await row.query_selector("a")
                    if not link_el:
                        continue

                    title = await link_el.inner_text()
                    href = await link_el.get_attribute("href")

                    # Try to get other fields from adjacent cells
                    cells = await row.query_selector_all("td, .column")
                    location = None
                    date_str = None

                    if len(cells) >= 2:
                        location = await cells[1].inner_text()
                    if len(cells) >= 3:
                        date_str = await cells[2].inner_text()

                    if title and title.strip():
                        job_url = href if href and href.startswith("http") else url
                        jobs.append({
                            "title": title.strip(),
                            "location": location.strip() if location else None,
                            "date_str": date_str.strip() if date_str else None,
                            "url": job_url,
                        })
                except Exception as e:
                    logger.debug(f"Failed to parse Taleo row: {e}")

            logger.info(f"Parsed {len(jobs)} listings from Taleo/CAPPS")
            return jobs

    def normalize(self, raw: dict) -> dict:
        posting_date = None
        if raw.get("date_str"):
            for fmt in ("%m/%d/%Y", "%m/%d/%y", "%b %d, %Y"):
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
