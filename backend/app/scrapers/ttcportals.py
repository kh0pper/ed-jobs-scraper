"""TTC Portals scraper (e.g., YES Prep Public Schools).

TTC Portals career pages are JS-rendered and protected by Cloudflare.
Uses session warming to bypass bot detection.
"""

import asyncio
import logging

from app.scrapers.base import BaseScraper
from app.scrapers.registry import register_scraper

logger = logging.getLogger(__name__)


@register_scraper("ttcportals")
class TtcPortalsScraper(BaseScraper):

    def scrape(self) -> list[dict]:
        return asyncio.get_event_loop().run_until_complete(self._scrape_async())

    async def _scrape_async(self) -> list[dict]:
        from app.scrapers.browser import get_browser, human_delay

        url = self.source.base_url
        logger.info(f"Fetching TTC Portals page: {url}")

        async with get_browser(timeout=60000) as browser:
            page = await browser.new_page()

            # Use session warming to bypass Cloudflare
            await browser.warm_session(page, url)

            # Check for Cloudflare challenge
            html = await page.content()
            if "verify you are human" in html.lower() or "cf-challenge" in html.lower():
                logger.warning("Cloudflare challenge detected, waiting for resolution...")
                await human_delay(5000, 10000)
                html = await page.content()

                if "verify you are human" in html.lower() or "cf-challenge" in html.lower():
                    logger.error("Cloudflare challenge not resolved after wait")
                    return []

            jobs = []
            listings = await page.query_selector_all(".job-item, .search-result, .opportunity, tr.job-row")

            if not listings:
                listings = await page.query_selector_all("[class*='job'], [class*='posting'], [class*='result']")

            for listing in listings:
                try:
                    title_el = await listing.query_selector("a, .job-title, h3, h4")
                    if not title_el:
                        continue

                    title = await title_el.inner_text()
                    href = await title_el.get_attribute("href")

                    location_el = await listing.query_selector(".location, .city")
                    location = await location_el.inner_text() if location_el else None

                    if title and title.strip():
                        job_url = href if href and href.startswith("http") else url
                        jobs.append({
                            "title": title.strip(),
                            "location": location.strip() if location else None,
                            "url": job_url,
                        })
                except Exception as e:
                    logger.debug(f"Failed to parse TTC listing: {e}")

            logger.info(f"Parsed {len(jobs)} listings from TTC Portals")
            return jobs

    def normalize(self, raw: dict) -> dict:
        return {
            "title": raw["title"],
            "application_url": raw["url"],
            "location": raw.get("location"),
        }
