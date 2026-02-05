"""SchoolSpring scraper.

URL pattern: https://{slug}.schoolspring.com/
SchoolSpring is a SPA with card-based job listings.
Each card has: title (.card-title), school (.card-text:nth-child(2)),
location (.card-text:nth-child(3)), date (.card-text:nth-child(4)).
Jobs load 25 per batch via a "More Jobs" button at the bottom of #jobListPanel.
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

            # Try to extract expected total from page text (e.g. "326 results")
            try:
                body_text = await page.inner_text("body")
                match = re.search(r"(\d+)\s+results?", body_text)
                expected_total = int(match.group(1)) if match else None
                if expected_total:
                    logger.info(f"SchoolSpring reports {expected_total} total results")
            except Exception:
                expected_total = None

            # Dismiss any overlay dialog that may block clicks
            try:
                overlay = await page.query_selector("pds-dialog .pds-overlay")
                if overlay:
                    await page.evaluate("""() => {
                        const dialogs = document.querySelectorAll('pds-dialog');
                        dialogs.forEach(d => d.style.display = 'none');
                    }""")
                    logger.info("Dismissed overlay dialog")
            except Exception:
                pass

            # Click "More Jobs" button repeatedly to load all jobs (25 per batch)
            max_clicks = 50  # Safety limit (~1250 jobs max)
            stall_count = 0
            prev_count = 0

            for i in range(max_clicks):
                cards = await page.query_selector_all(".card")
                current_count = len(cards)

                if current_count == prev_count:
                    stall_count += 1
                    if stall_count >= 3:
                        logger.info(f"No new cards after {i} clicks, stopping at {current_count}")
                        break
                else:
                    stall_count = 0
                    if i % 5 == 0:
                        logger.info(f"SchoolSpring progress: {current_count} cards loaded")

                prev_count = current_count

                # Find and click the "More Jobs" button
                more_btn = await page.query_selector("button:has-text('More Jobs')")
                if not more_btn:
                    logger.info(f"No 'More Jobs' button found, done at {current_count} cards")
                    break

                # Scroll button into view and click (force to bypass any remaining overlays)
                await more_btn.scroll_into_view_if_needed()
                await human_delay(300, 600)
                await more_btn.click(force=True)

                # Wait for new cards to appear
                try:
                    await page.wait_for_function(
                        f"document.querySelectorAll('.card').length > {current_count}",
                        timeout=10000,
                    )
                except Exception:
                    pass  # Timeout handled by stall_count

                await human_delay(500, 1000)

            # Parse all cards
            cards = await page.query_selector_all(".card")
            logger.info(f"Found {len(cards)} card elements after loading")

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

            logger.info(f"Parsed {len(jobs)} listings from SchoolSpring"
                        + (f" (expected {expected_total})" if expected_total else ""))
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

        # Parse state from location (e.g., "Spring, TX" -> "TX")
        state = "TX"  # Default to TX for Texas-based org
        if raw.get("location"):
            loc = raw["location"].upper()
            match = re.search(r"\b([A-Z]{2})\s*$", loc)
            if match:
                state = match.group(1)

        return {
            "title": raw["title"],
            "application_url": raw["url"],
            "location": raw.get("location"),
            "city": city,
            "state": state,
            "campus": raw.get("school"),  # School name maps to campus
            "posting_date": posting_date,
        }
