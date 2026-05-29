"""Skyward Qmlativ (Vue.js SPA) applicant-tracking scraper.

Modern Skyward districts serve their job board as a Vue SPA at
``/{tenant}/ApplicantTracking/JobBoard/ViewJobPostings``. The board is driven
by a **stateless** form-encoded POST to ``/{tenant}/SkySys/VueData/GetData/``
that returns columnar JSON. No cookies, no CSRF token — every parameter the
POST needs is rendered into the initial page inside a single ``data-skyvue``
attribute (HTML-entity-encoded JSON with ``hashes`` + ``features``). We echo
those values back verbatim (the server-precomputed hashes validate them), so
plain httpx works — no browser automation needed.

Registered as a SEPARATE platform from classic ``skyward`` (WebSpeed zD[]
arrays); the two share nothing but a vendor name.

Response shape (columnar — parallel arrays indexed by row):
  {"values": {"JobTitle": [...], "BuildingCodes": [...], "JobPostingID": [...],
              "JobCategory": {"Description": [...]}, "EmploymentType": [...],
              "ApplicantPostedDate": [...], "ApplicantDeadline": [...],
              "PayDisplayString": [...], "Summary": [...], "$repeat": [n]}}

Pagination is keyset "InfiniteScroll": page 1 = ``pagingPage=first`` /
``pagingIdentifierValue=""``; each subsequent page = ``pagingPage=next`` /
``pagingIdentifierValue=<last JobPostingID returned>``.
"""

import html
import json
import logging
import re
import time
from datetime import datetime
from urllib.parse import urlparse

import httpx

from app.scrapers.base import BaseScraper
from app.scrapers.registry import register_scraper

logger = logging.getLogger(__name__)

_SKYVUE_RE = re.compile(r'data-skyvue="([^"]+)"')
_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36")
_MAX_PAGES = 100  # safety cap (pageSize 20 -> 2000 jobs)
_OPEN_STATUSES = ("until filled", "open until filled", "open year round", "continuous", "")
_DATE_FORMATS = ("%m/%d/%Y", "%m/%d/%y", "%Y-%m-%d")


def _json_compact(obj) -> str:
    """Match JS JSON.stringify: no spaces, no non-ASCII escaping (preserves
    the byte sequence the server hashed)."""
    return json.dumps(obj, separators=(",", ":"), ensure_ascii=False)


@register_scraper("skyward_vue")
class SkywardVueScraper(BaseScraper):

    def scrape(self) -> list[dict]:
        board_url = self.source.base_url
        parsed = urlparse(board_url)
        # base = {scheme}://{host}/{tenant}
        tenant = parsed.path.split("/ApplicantTracking", 1)[0]
        base = f"{parsed.scheme}://{parsed.netloc}{tenant}"
        get_data_url = f"{base}/SkySys/VueData/GetData/"
        logger.info("[skyward_vue/%s] Board: %s", self.source.slug, board_url)

        headers = {"User-Agent": _UA}
        post_headers = {
            **headers,
            "X-Requested-With": "XMLHttpRequest",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "Origin": f"{parsed.scheme}://{parsed.netloc}",
            "Referer": board_url,
        }

        with httpx.Client(timeout=45, follow_redirects=True, headers=headers) as client:
            page_html = self._get_with_retry(client, board_url)
            config = self._extract_config(page_html)
            if not config:
                logger.error("[skyward_vue/%s] Could not find data-skyvue config", self.source.slug)
                return []

            f = config["features"]
            hashes = config["hashes"]
            page_size = f.get("pagingType", {}).get("pageSize", 20)

            base_body = {
                "dataSourceType": f["dataSource"]["typeIdentifier"],
                "identifierField": f["dataSource"]["identifierField"],
                "dataSourceParametersHash": hashes["dataSource"],
                "dataSourceParameters": _json_compact(f["dataSource"]),
                "dataSourceFields": _json_compact(f["fields"]),
                "dataSourceFieldsHash": hashes["fields"],
                "filterTypeIdentifier": f["filterType"]["typeIdentifier"],
                "filterType": _json_compact(f["filterType"]),
                "filterTypeHash": hashes["filterType"],
                "pagingTypeIdentifier": f["pagingType"]["typeIdentifier"],
                "pagingType": _json_compact(f["pagingType"]),
            }

            jobs = []
            seen = set()
            page, idv = "first", ""
            for n in range(_MAX_PAGES):
                body = {**base_body, "pagingPage": page, "pagingIdentifierValue": idv}
                resp = client.post(get_data_url, data=body, headers=post_headers)
                resp.raise_for_status()
                values = resp.json().get("values", {})
                ids = values.get("JobPostingID", [])
                if not ids:
                    break

                rows = self._columns_to_rows(values, base_url=board_url)
                fresh = [r for r in rows if r["external_id"] not in seen]
                if not fresh:
                    break
                for r in fresh:
                    seen.add(r["external_id"])
                jobs.extend(fresh)

                count = (values.get("$repeat") or [len(ids)])[0]
                if count < page_size:
                    break
                page, idv = "next", str(ids[-1])
                time.sleep(0.3)
            else:
                logger.warning("[skyward_vue/%s] Hit page cap %d", self.source.slug, _MAX_PAGES)

            logger.info("[skyward_vue/%s] Parsed %d job postings", self.source.slug, len(jobs))
            return jobs

    @staticmethod
    def _get_with_retry(client: httpx.Client, url: str) -> str:
        for attempt in range(3):
            try:
                r = client.get(url)
                r.raise_for_status()
                return r.text
            except (httpx.TimeoutException, httpx.HTTPError, httpx.NetworkError) as e:
                if attempt == 2:
                    raise
                wait = 5 * (3 ** attempt)
                logger.warning("[skyward_vue] GET attempt %d/3 failed (%s); retry in %ds",
                               attempt + 1, e, wait)
                time.sleep(wait)
        return ""

    @staticmethod
    def _extract_config(page_html: str) -> dict | None:
        m = _SKYVUE_RE.search(page_html)
        if not m:
            return None
        try:
            return json.loads(html.unescape(m.group(1)))
        except (ValueError, json.JSONDecodeError):
            return None

    @staticmethod
    def _columns_to_rows(values: dict, base_url: str) -> list[dict]:
        ids = values.get("JobPostingID", [])

        def col(name):
            return values.get(name) or [None] * len(ids)

        titles = col("JobTitle")
        buildings = col("BuildingCodes")
        categories = (values.get("JobCategory") or {}).get("Description") or [None] * len(ids)
        emp_types = col("EmploymentType")
        posted = col("ApplicantPostedDate")
        deadline = col("ApplicantDeadline")
        pay = col("PayDisplayString")
        summary = col("Summary")

        rows = []
        for i, jid in enumerate(ids):
            title = (titles[i] or "").strip() if i < len(titles) else ""
            if not title:
                continue
            rows.append({
                "external_id": str(jid),
                "title": title,
                "campus": (buildings[i] or "").strip() if i < len(buildings) else None,
                "raw_category": (categories[i] or "").strip() if i < len(categories) else None,
                "employment_type": (emp_types[i] or "").strip() if i < len(emp_types) else None,
                "posted": (posted[i] or "").strip() if i < len(posted) else None,
                "deadline": (deadline[i] or "").strip() if i < len(deadline) else None,
                "pay": (pay[i] or "").strip() if i < len(pay) else None,
                "summary": (summary[i] or "").strip() if i < len(summary) else None,
                "base_url": base_url,
            })
        return rows

    def normalize(self, raw: dict) -> dict:
        result = {
            "title": raw["title"],
            "application_url": f"{raw['base_url']}#job={raw['external_id']}",
            "state": "TX",
            "external_id": raw["external_id"],
        }

        campus = raw.get("campus")
        if campus and campus.lower() not in ("district wide", "n/a") and "district wide" not in campus.lower():
            result["campus"] = campus
        if raw.get("raw_category"):
            result["raw_category"] = raw["raw_category"]
        if raw.get("employment_type"):
            result["employment_type"] = raw["employment_type"].lower().replace(" ", "_")
        if raw.get("summary"):
            result["description"] = raw["summary"]
        if raw.get("pay"):
            result["salary_text"] = raw["pay"]

        posted = self._parse_date(raw.get("posted"))
        if posted:
            result["posting_date"] = posted
        closing = self._parse_date(raw.get("deadline"))
        if closing:
            result["closing_date"] = closing
        elif raw.get("deadline") and raw["deadline"].lower() not in _OPEN_STATUSES:
            result["extra_data"] = {"deadline_status": raw["deadline"]}

        return result

    @staticmethod
    def _parse_date(text: str | None) -> datetime | None:
        if not text or text.lower().strip() in _OPEN_STATUSES:
            return None
        for fmt in _DATE_FORMATS:
            try:
                return datetime.strptime(text.strip(), fmt)
            except ValueError:
                continue
        return None
