"""SchoolSpring scraper.

URL pattern: https://{slug}.schoolspring.com/
SchoolSpring is a Vue SPA with card-based job listings.
Each card has: title (.card-title), school (.card-text:nth-child(2)),
location (.card-text:nth-child(3)), date (.card-text:nth-child(4)).
Jobs load via infinite scroll (25 per batch).
"""

import asyncio
import logging
import re
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

            # Scroll to load all jobs (infinite scroll, 25 per batch)
            prev_count = 0
            max_scrolls = 50  # Safety limit (~1250 jobs max)
            for _ in range(max_scrolls):
                cards = await page.query_selector_all(".card")
                if len(cards) == prev_count:
                    break
                prev_count = len(cards)
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                await human_delay(800, 1500)

            # Parse all cards
            cards = await page.query_selector_all(".card")
            logger.info(f"Found {len(cards)} card elements")

            jobs = []
            for card in cards:
                try:
                    title_el = await card.query_selector(".card-title")
                    title = await title_el.inner_text() if title_el else None
                    if not title:
                        continue

                    # card-text elements: school, location, date
                    texts = await card.query_selector_all(".card-text")
                    school = await texts[0].inner_text() if len(texts) > 0 else None
                    location = await texts[1].inner_text() if len(texts) > 1 else None
                    date_str = await texts[2].inner_text() if len(texts) > 2 else None

                    jobs.append({
                        "title": title.strip(),
                        "school": school.strip() if school else None,
                        "location": location.strip() if location else None,
                        "date_str": date_str.strip() if date_str else None,
                        "url": url,  # No per-job URLs available from listing
                    })
                except Exception as e:
                    logger.debug(f"Failed to parse card: {e}")

            logger.info(f"Parsed {len(jobs)} listings from SchoolSpring")
            return jobs

    def normalize(self, raw: dict) -> dict:
        posting_date = None
        if raw.get("date_str"):
            date_str = raw["date_str"]
            # Handle "Yesterday", "Today", etc.
            if "yesterday" in date_str.lower() or "today" in date_str.lower():
                posting_date = datetime.utcnow()
            else:
                # Strip timezone info: "Feb 03, 2026 6:00 AM (UTC)"
                clean = re.sub(r"\s*\(.*?\)\s*$", "", date_str)
                for fmt in ("%b %d, %Y %I:%M %p", "%b %d, %Y", "%m/%d/%Y", "%B %d, %Y", "%Y-%m-%d"):
                    try:
                        posting_date = datetime.strptime(clean, fmt)
                        break
                    except ValueError:
                        continue

        city = None
        if raw.get("location"):
            parts = raw["location"].split(",")
            if parts:
                city = parts[0].strip()

        return {
            "title": raw["title"],
            "application_url": raw["url"],
            "location": raw.get("location"),
            "city": city,
            "department": raw.get("school"),
            "posting_date": posting_date,
        }
