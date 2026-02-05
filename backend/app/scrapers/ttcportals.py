"""TTC Portals scraper (e.g., YES Prep Public Schools).

TTC Portals career pages are JS-rendered and protected by Cloudflare Turnstile.
Uses Camoufox anti-detect browser to bypass bot detection.
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
        from app.services.turnstile_solver import TurnstileSolver

        url = self.source.base_url
        logger.info(f"Fetching TTC Portals page: {url}")

        # Use Camoufox for Cloudflare bypass
        solver = TurnstileSolver(headless=True)

        try:
            async with solver.get_browser() as browser:
                page = await browser.new_page()

                # Navigate with Turnstile bypass
                html = await solver.navigate_with_turnstile_bypass(page, url)

                # Check if we got past Cloudflare
                if "verify you are human" in html.lower() or "cf-challenge" in html.lower():
                    logger.error("Cloudflare challenge not resolved")
                    await page.close()
                    return []

                jobs = await self._extract_jobs(page)

                await page.close()
                return jobs

        except ImportError:
            logger.error("Camoufox not installed. TTC Portals scraper requires: pip install camoufox[geoip]")
            return []
        except Exception as e:
            logger.error(f"TTC Portals scraping failed: {e}")
            return []

    async def _extract_jobs(self, page) -> list[dict]:
        """Extract job listings from the page."""
        jobs = []

        # Try various selectors for job listings
        selectors = [
            ".job-item",
            ".search-result",
            ".opportunity",
            "tr.job-row",
            "[class*='job']",
            "[class*='posting']",
            "[class*='result']",
            "article",
            ".card",
        ]

        listings = []
        for selector in selectors:
            listings = await page.query_selector_all(selector)
            if listings:
                logger.debug(f"Found {len(listings)} elements with selector: {selector}")
                break

        if not listings:
            # Try to find any links that look like job postings
            all_links = await page.query_selector_all("a")
            for link in all_links:
                try:
                    href = await link.get_attribute("href")
                    text = await link.inner_text()

                    if href and text and len(text.strip()) > 10:
                        # Check if it looks like a job link
                        job_indicators = ["job", "position", "career", "apply", "posting"]
                        if any(ind in (href or "").lower() or ind in text.lower() for ind in job_indicators):
                            job_url = href if href.startswith("http") else f"{self.source.base_url.rstrip('/')}/{href.lstrip('/')}"
                            jobs.append({
                                "title": text.strip(),
                                "location": None,
                                "url": job_url,
                            })
                except Exception:
                    pass

            logger.info(f"Found {len(jobs)} potential job links")
            return jobs

        # Extract jobs from found listings
        for listing in listings:
            try:
                # Try various title selectors
                title_selectors = ["a", ".job-title", "h3", "h4", "h2", ".title"]
                title_el = None
                for sel in title_selectors:
                    title_el = await listing.query_selector(sel)
                    if title_el:
                        break

                if not title_el:
                    continue

                title = await title_el.inner_text()
                href = await title_el.get_attribute("href")

                # Try to get location
                location = None
                location_selectors = [".location", ".city", ".place", "[class*='location']"]
                for sel in location_selectors:
                    location_el = await listing.query_selector(sel)
                    if location_el:
                        location = await location_el.inner_text()
                        break

                if title and title.strip():
                    clean_title = title.strip()
                    # Skip pagination/navigation links
                    skip_patterns = ["view more", "load more", "see all", "next page", "previous"]
                    if any(pat in clean_title.lower() for pat in skip_patterns):
                        continue

                    job_url = href if href and href.startswith("http") else self.source.base_url
                    jobs.append({
                        "title": clean_title,
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
            "state": "TX",  # TTC Portals sources are Texas orgs
        }
