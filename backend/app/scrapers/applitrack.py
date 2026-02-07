"""Applitrack/Frontline scraper.

Handles all districts using the Applitrack platform.
The main data endpoint is: /jobpostings/Output.asp?all=1
Each job appears as a table with class='title' containing:
  - Cell 1: Job title (text)
  - Cell 2: "JobID: XXXXX"
Followed by a sibling <div> with <li> elements for metadata:
  - Position Type, Date Posted, Location, optionally Closing Date
"""

import logging
import re
from datetime import datetime, timezone

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
        _warned_structure = False

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

            # Extract category from onclick="applyFor('ID','Category','Subcategory')"
            # This is the most reliable source — present on all districts
            raw_category = None
            apply_btn = table.find("input", onclick=True)
            if apply_btn:
                onclick = apply_btn.get("onclick", "")
                cat_match = re.search(
                    r"applyFor\([^,]+,\s*'([^']*)',\s*'([^']*)'",
                    onclick,
                )
                if cat_match:
                    cat, subcat = cat_match.group(1), cat_match.group(2)
                    if subcat:
                        raw_category = f"{cat}/{subcat}"
                    elif cat:
                        raw_category = cat

            # Extract metadata from the sibling <div> with <li> elements
            location = None
            date_posted = None
            closing_date_text = None

            meta_div = table.find_next_sibling("div")
            if meta_div:
                for li in meta_div.find_all("li"):
                    label_span = li.find("span", class_="label")
                    if not label_span:
                        continue
                    label_text = label_span.get_text(strip=True).lower()

                    # Collect all <span class='normal'> text within this <li>
                    normal_spans = li.find_all("span", class_="normal")
                    value = " ".join(s.get_text(strip=True) for s in normal_spans).strip()
                    if not value:
                        continue

                    if "position type" in label_text:
                        # Override with <li> value if present (more detailed)
                        raw_category = value
                    elif "location" in label_text:
                        location = value
                    elif "date posted" in label_text:
                        date_posted = value
                    elif "closing date" in label_text:
                        closing_date_text = value
            elif not _warned_structure:
                logger.warning(
                    f"[{slug}] No metadata <div> found after title table — "
                    "HTML structure may have changed"
                )
                _warned_structure = True

            jobs.append({
                "title": title,
                "job_id": job_id,
                "url": detail_url,
                "raw_category": raw_category,
                "location": location,
                "date_posted": date_posted,
                "closing_date_text": closing_date_text,
            })

        logger.info(f"Parsed {len(jobs)} listings from Applitrack Output.asp")
        return jobs

    def normalize(self, raw: dict) -> dict:
        result = {
            "title": raw["title"],
            "application_url": raw["url"],
            "raw_category": raw.get("raw_category"),
            "external_id": raw.get("job_id"),
            "state": "TX",  # Applitrack sources are Texas districts
        }

        # Location → campus (these are school/building names, not addresses)
        if raw.get("location"):
            result["campus"] = raw["location"]

        # Date Posted → posting_date (M/D/YYYY format, stored as UTC midnight)
        if raw.get("date_posted"):
            try:
                dt = datetime.strptime(raw["date_posted"], "%m/%d/%Y")
                result["posting_date"] = dt.replace(tzinfo=timezone.utc)
            except ValueError:
                pass

        return result
