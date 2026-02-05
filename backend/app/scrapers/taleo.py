"""Taleo/CAPPS scraper (e.g., Texas Education Agency).

CAPPS (Centralized Accounting and Payroll/Personnel System) uses Oracle Taleo
for state agency job postings. Table rows have: [icons, title, location, date, actions].
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
            await page.goto(url, wait_until="domcontentloaded")
            await human_delay(3000, 5000)

            jobs = []

            # Each job row has a link to jobdetail
            links = await page.query_selector_all("a[href*='jobdetail']")
            for link in links:
                try:
                    title = await link.inner_text()
                    href = await link.get_attribute("href") or ""

                    # Navigate up to the row and get sibling cells
                    row_data = await link.evaluate("""el => {
                        const row = el.closest('tr');
                        if (!row) return null;
                        const cells = row.querySelectorAll('td');
                        return {
                            location: cells.length > 2 ? cells[2].innerText.trim() : '',
                            date: cells.length > 3 ? cells[3].innerText.trim() : '',
                        };
                    }""")

                    if not title or not title.strip():
                        continue

                    job_url = href if href.startswith("http") else f"https://capps.taleo.net{href}" if href.startswith("/") else url

                    jobs.append({
                        "title": title.strip(),
                        "location": row_data["location"] if row_data else None,
                        "date_str": row_data["date"] if row_data else None,
                        "url": job_url,
                    })
                except Exception as e:
                    logger.debug(f"Failed to parse Taleo row: {e}")

            logger.info(f"Parsed {len(jobs)} listings from Taleo/CAPPS")
            return jobs

    def normalize(self, raw: dict) -> dict:
        posting_date = None
        if raw.get("date_str"):
            for fmt in ("%b %d, %Y", "%m/%d/%Y", "%m/%d/%y", "%B %d, %Y"):
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
