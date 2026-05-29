"""Frontline ERP / TEAMS applicant-tracking scraper.

Frontline's ERP & SIS suite (formerly TEAMS / Aspex) powers the public
"Browse Job Postings" board at ``/submission/EntryPointBrowseJobPostingsAction.do``.
Despite the JS-heavy chrome, the board is **fully server-rendered**: every
category and every posting is present in the initial HTML as a set of grid
tables (``<tbody id="{Category}jobsTableBodyTable">``). So plain httpx + BS4
works — no browser automation needed.

Hosting varies (``{slug}.erp.frontlineeducation.com`` for cloud tenants,
self-hosted ``teams.{district}.net`` for older installs), but the path and
markup are identical across both.

Row anatomy (columns: Position | Organization | Application Deadline |
Posting ID | Job Description | Apply):

  <tr id="{Cat}jobsTable-row-{n}" jobId="6897">
    <td title="Assistant General Counsel">Assistant General Counsel</td>  # title
    <td title="Legal">Legal</td>                                          # organization
    <td title="Open Until Filled">Open Until Filled</td>                  # deadline/status
    <td><a class="postingId">6897</a></td>                                # posting id (optional)
    <td><a class="jobDescriptionLink" link="...pdf">Job Description</a></td>
    <td><a class="jobApplyLink">Apply</a></td>

Two row flavours:
  * Dated postings — non-empty ``jobId`` and a numeric Posting ID.
  * Evergreen pools — ``jobId=""``, "Open Year Round", standing vacancies the
    district keeps advertising. Both are real opportunities, both are kept.

The on-portal "Apply" link is generic (it routes to the login/home action,
not a per-posting deep link), so we mint a stable, unique ``application_url``
from the browse page plus a fragment key — the same approach skyward.py uses.
"""

import logging
import re
import time
from datetime import datetime
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup

from app.scrapers.base import BaseScraper
from app.scrapers.registry import register_scraper

logger = logging.getLogger(__name__)

_BODY_ID_RE = re.compile(r"(?P<cat>\w+)jobsTableBodyTable$")
_CAMEL_RE = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
_NO_POSITIONS = "no positions available"

# Status phrases that are NOT real dates — keep as status text, not closing_date.
_OPEN_STATUSES = ("open year round", "open until filled", "continuous")

_DATE_FORMATS = ("%m-%d-%Y", "%m-%d-%y", "%m/%d/%Y", "%m/%d/%y",
                 "%b %d, %Y", "%B %d, %Y", "%Y-%m-%d")


def _slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def _category_from_id(cat_id: str) -> str:
    """Fallback human label from a camelCase table id (e.g. ElementaryTeachers)."""
    label = _CAMEL_RE.sub(" ", cat_id)
    return re.sub(r"\s+", " ", label).strip()


@register_scraper("frontline_erp")
class FrontlineErpScraper(BaseScraper):

    def scrape(self) -> list[dict]:
        url = self.source.base_url
        logger.info("[frontline_erp/%s] Fetching: %s", self.source.slug, url)

        resp = None
        for attempt in range(3):
            try:
                resp = httpx.get(
                    url,
                    timeout=45,
                    follow_redirects=True,
                    headers={
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
                    },
                )
                resp.raise_for_status()
                break
            except (httpx.TimeoutException, httpx.HTTPError, httpx.NetworkError) as e:
                if attempt == 2:
                    raise
                wait = 5 * (3 ** attempt)
                logger.warning("[frontline_erp/%s] Attempt %d/3 failed (%s); retrying in %ds",
                               self.source.slug, attempt + 1, e, wait)
                time.sleep(wait)
        assert resp is not None

        soup = BeautifulSoup(resp.text, "lxml")
        # Origin for building stable per-posting URLs (handles redirected host).
        origin = "{0.scheme}://{0.netloc}".format(urlparse(str(resp.url)))

        jobs = []
        bodies = soup.find_all("tbody", id=_BODY_ID_RE)
        for body in bodies:
            cat_id = _BODY_ID_RE.match(body.get("id", "")).group("cat")
            category = self._category_label(body, cat_id)

            for tr in body.find_all("tr"):
                cells = tr.find_all("td")
                if len(cells) < 3:
                    continue

                title = cells[0].get("title") or cells[0].get_text(strip=True)
                title = (title or "").replace("\xa0", " ").strip()
                if not title:
                    continue

                organization = self._cell(cells, 1)
                deadline = self._cell(cells, 2)

                # lxml lowercases attribute names, so the source's jobId -> jobid.
                job_id = (tr.get("jobid") or "").strip()
                posting_id = ""
                pid = tr.find("a", class_="postingId")
                if pid:
                    posting_id = pid.get_text(strip=True)

                desc_link = None
                dl = tr.find("a", class_="jobDescriptionLink")
                if dl and dl.get("link"):
                    desc_link = dl["link"].strip()

                jobs.append({
                    "title": title,
                    "category": category,
                    "organization": organization,
                    "deadline": deadline,
                    "job_id": job_id,
                    "posting_id": posting_id,
                    "desc_link": desc_link,
                    "origin": origin,
                })

        if not jobs and _NO_POSITIONS in resp.text.lower():
            logger.info("[frontline_erp/%s] Board reports no open positions", self.source.slug)
            return []

        logger.info("[frontline_erp/%s] Parsed %d listings across %d categories",
                    self.source.slug, len(jobs), len(bodies))
        return jobs

    @staticmethod
    def _cell(cells, idx: int) -> str | None:
        if len(cells) <= idx:
            return None
        td = cells[idx]
        val = (td.get("title") or td.get_text(strip=True) or "").replace("\xa0", " ").strip()
        return val or None

    @staticmethod
    def _category_label(body, cat_id: str) -> str:
        """Prefer the panel's visible <span class="sst-title">, else split the id."""
        container = body.find_parent(class_="tablePanelContainer")
        if container:
            title_el = container.find("span", class_="sst-title")
            if title_el:
                label = title_el.get_text(strip=True)
                if label:
                    return label
        return _category_from_id(cat_id)

    def normalize(self, raw: dict) -> dict:
        origin = raw["origin"]
        browse = f"{origin}/submission/EntryPointBrowseJobPostingsAction.do?applicantType=external"

        # Stable, unique application URL. jobId is the server's stable key for
        # dated postings; evergreen pools (jobId="") get a deterministic slug so
        # they dedup consistently across re-scrapes.
        if raw["job_id"]:
            key = f"job-{raw['job_id']}"
        else:
            key = "pool-" + _slugify(f"{raw['category']}-{raw['title']}-{raw.get('organization') or ''}")
        app_url = f"{browse}#{key}"

        result = {
            "title": raw["title"],
            "application_url": app_url,
            "state": "TX",
            "raw_category": raw["category"],
            "external_id": raw["job_id"] or raw["posting_id"] or None,
        }

        # The "Organization" column names the work location/building (e.g.
        # "Burges High School", "Legal"). Map it to campus so the geocoding
        # cascade can resolve real school buildings; is_geocodable_campus()
        # gates out admin-department values, which then inherit org coords.
        org = raw.get("organization")
        if org and org.lower() not in ("district wide", "n/a"):
            result["campus"] = org

        closing = self._parse_deadline(raw.get("deadline"))
        if closing:
            result["closing_date"] = closing

        extra = {}
        if raw.get("posting_id"):
            extra["posting_id"] = raw["posting_id"]
        if raw.get("desc_link"):
            extra["description_url"] = raw["desc_link"]
        if raw.get("deadline") and not closing:
            extra["status"] = raw["deadline"]
        if extra:
            result["extra_data"] = extra

        return result

    @staticmethod
    def _parse_deadline(text: str | None) -> datetime | None:
        if not text:
            return None
        if text.lower().strip() in _OPEN_STATUSES:
            return None
        for fmt in _DATE_FORMATS:
            try:
                return datetime.strptime(text.strip(), fmt)
            except ValueError:
                continue
        return None
