"""Applitrack/Frontline scraper.

Handles all districts using the Applitrack platform.
The main data endpoint is: /jobpostings/Output.asp?all=1
Each job appears as a table with class='title' containing:
  - Cell 1: Job title (text)
  - Cell 2: "JobID: XXXXX"
"""

import logging
import re

import httpx
from bs4 import BeautifulSoup

from app.scrapers.base import BaseScraper
from app.scrapers.registry import register_scraper

logger = logging.getLogger(__name__)

APPLITRACK_BASE = "https://www.applitrack.com"


@register_scraper("applitrack")
class ApplitrackScraper(BaseScraper):

    def scrape(self) -> list[dict]:
        slug = self.source.slug
        # The Output.asp endpoint returns all jobs in one page
        url = f"{APPLITRACK_BASE}/{slug}/onlineapp/jobpostings/Output.asp?all=1"

        logger.info(f"Fetching Applitrack Output.asp: {url}")

        response = httpx.get(
            url,
            timeout=60,
            follow_redirects=True,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
            },
        )
        response.raise_for_status()

        soup = BeautifulSoup(response.text, "lxml")
        jobs = []

        # Each job is a table with class containing 'title'
        # Structure: <table class="'title'"><tr><td>Job Title</td><td>JobID: 12345</td></tr></table>
        for table in soup.find_all("table"):
            cls = str(table.get("class", []))
            if "title" not in cls.lower():
                continue

            rows = table.find_all("tr")
            if not rows:
                continue

            cells = rows[0].find_all("td")
            if not cells:
                continue

            title = cells[0].get_text(strip=True)
            if not title:
                continue

            # Extract JobID from second cell
            job_id = None
            if len(cells) > 1:
                id_text = cells[1].get_text(strip=True)
                match = re.search(r"JobID:\s*(\d+)", id_text)
                if match:
                    job_id = match.group(1)

            # Construct the detail URL
            if job_id:
                detail_url = (
                    f"{APPLITRACK_BASE}/{slug}/onlineapp/default.aspx"
                    f"?AppliTrackJobId={job_id}&AppliTrackLayoutMode=detail&AppliTrackViewPosting=1"
                )
            else:
                detail_url = f"{APPLITRACK_BASE}/{slug}/onlineapp/default.aspx"

            # Try to find category from surrounding context
            # The category is in the preceding section header
            raw_category = None

            jobs.append({
                "title": title,
                "job_id": job_id,
                "url": detail_url,
                "raw_category": raw_category,
            })

        logger.info(f"Parsed {len(jobs)} listings from Applitrack Output.asp")
        return jobs

    def normalize(self, raw: dict) -> dict:
        return {
            "title": raw["title"],
            "application_url": raw["url"],
            "raw_category": raw.get("raw_category"),
            "external_id": raw.get("job_id"),
        }
