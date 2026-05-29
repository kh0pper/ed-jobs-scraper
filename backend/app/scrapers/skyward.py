"""Skyward applicant tracking scraper (classic WebSpeed variant).

Skyward's classic interface renders all job listings in a single GET
response, embedding them as JavaScript arrays: zD[n] = ["", checkbox, ...].
Column order varies per district; we parse a metadata string to map them.

Handles both self-hosted (cgiip.exe) and ISCorp-hosted (wsisa.dll) variants.
Does NOT handle the Vue.js SPA variant (Business/ApplicantTracking/).
"""

import csv
import io
import logging
import re
import time

import httpx

from app.scrapers.base import BaseScraper
from app.scrapers.registry import register_scraper

logger = logging.getLogger(__name__)

_ZD_PATTERN = re.compile(r'zD\[\d+\]\s*=\s*\[([^\]]+)\]')
_COL_META_PATTERN = re.compile(r'Position Description\^character[^\n]+')

_FIELD_MAP = {
    "Position Description": "raw_category",
    "Assignment Description": "title",
    "Location": "campus",
    "Department": "department",
    "Position ID": "external_id",
    "Application Deadline": "closing_date_str",
    "School Year": "school_year",
    "Employment Type": "employment_type",
    "Group": "group",
    "Grade To": "grade_to",
    "Grade From": "grade_from",
}


def _parse_columns(html: str) -> tuple[list[str], int]:
    """Extract ordered column names and data offset from the page.

    Returns (column_names, offset) where offset is the starting index
    in each zD array for the first metadata column. Typically 2 (skip
    empty + checkbox) unless a "Category" header column adds +1.
    """
    m = _COL_META_PATTERN.search(html)
    if not m:
        return [], 2
    raw = m.group()
    cols = []
    for part in raw.split("*^"):
        name = part.split("^")[0].strip()
        if name:
            cols.append(name)

    offset = 2
    if ">Category<" in html:
        cat_pos = html.find(">Category<")
        pd_pos = html.find(">Position Description<")
        if cat_pos != -1 and (pd_pos == -1 or cat_pos < pd_pos):
            offset = 3

    return cols, offset


def _parse_zd_entries(html: str) -> list[list[str]]:
    """Parse all zD[n] = [...] JavaScript array entries."""
    entries = []
    for m in _ZD_PATTERN.finditer(html):
        reader = csv.reader(io.StringIO(m.group(1)))
        try:
            row = next(reader)
            entries.append(row)
        except StopIteration:
            continue
    return entries


@register_scraper("skyward")
class SkywardScraper(BaseScraper):

    def scrape(self) -> list[dict]:
        url = self.source.base_url
        logger.info("[skyward/%s] Fetching: %s", self.source.slug, url)

        resp = None
        for attempt in range(3):
            try:
                resp = httpx.get(
                    url,
                    timeout=30,
                    follow_redirects=True,
                    headers={
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/121.0.0.0 Safari/537.36",
                    },
                )
                resp.raise_for_status()
                break
            except (httpx.TimeoutException, httpx.HTTPError, httpx.NetworkError) as e:
                if attempt == 2:
                    raise
                wait = 5 * (3 ** attempt)
                logger.warning("[skyward/%s] Attempt %d/3 failed (%s); retrying in %ds",
                               self.source.slug, attempt + 1, e, wait)
                time.sleep(wait)
        assert resp is not None

        columns, offset = _parse_columns(resp.text)
        if not columns:
            logger.error("[skyward/%s] Could not parse column metadata", self.source.slug)
            return []

        entries = _parse_zd_entries(resp.text)
        logger.info("[skyward/%s] Parsed %d columns (offset=%d), %d entries",
                     self.source.slug, len(columns), offset, len(entries))

        jobs = []
        for row in entries:
            data_cells = row[offset:]
            if len(data_cells) < len(columns):
                continue

            record = {}
            for i, col_name in enumerate(columns):
                field = _FIELD_MAP.get(col_name)
                if field:
                    val = data_cells[i].strip()
                    if val and val != "&nbsp;":
                        record[field] = val

            if not record.get("title"):
                if record.get("raw_category"):
                    record["title"] = record["raw_category"]
                else:
                    continue

            record["_base_url"] = url
            jobs.append(record)

        logger.info("[skyward/%s] Produced %d job records", self.source.slug, len(jobs))
        return jobs

    def normalize(self, raw: dict) -> dict:
        base = raw.pop("_base_url", self.source.base_url)
        ext_id = raw.get("external_id", "")
        app_url = f"{base}#pos={ext_id}" if ext_id else base

        result = {
            "title": raw["title"],
            "application_url": app_url,
            "state": "TX",
            "external_id": ext_id,
        }

        if raw.get("campus"):
            result["campus"] = raw["campus"]
        if raw.get("department"):
            result["department"] = raw["department"]
        if raw.get("raw_category"):
            result["raw_category"] = raw["raw_category"]
        if raw.get("employment_type"):
            result["employment_type"] = raw["employment_type"].lower().replace(" ", "_")

        return result
