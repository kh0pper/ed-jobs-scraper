"""SchoolSpring scraper — uses the public api.schoolspring.com JSON API.

Earlier versions used Camoufox + DOM scraping of the SPA's `.card` elements,
which (a) was slow because of `wait_until="networkidle"` against an SPA that
never settles, and (b) had a critical data-loss bug: every job from a card
got `application_url = self.source.base_url` (the tenant root), so all jobs
hashed to the same `url_hash` and clobbered each other in `_save_posting`.
Result: only 1 row per tenant in `job_postings` despite scrapes returning
hundreds of jobs each cycle.

The SchoolSpring SPA is backed by a clean JSON API:
- `GET /api/Jobs/GetPagedJobsWithSearch?domainName={host}&page=N&size=100`
   returns `{value: {jobsList: [{jobId, employer, title, location, displayDate}]}}`.
- `GET /api/Jobs/{jobId}?domainName={host}` returns full detail including
   `infoURL` (the district's actual apply page on TalentEd / TEDK12 / etc.)
   and `jobDescription` (rich HTML).

Tenant scoping comes from either a `Referer: https://{host}/` header OR
the `domainName=<host>` query param (we use the latter — explicit + cache-friendly).

Per-job detail is only fetched for new `jobId`s — existing jobs reuse their
stored `application_url`, keeping steady-state cost low.
"""

import logging
import time
from datetime import datetime
from typing import Iterator
from urllib.parse import urlparse

import httpx

from app.models.job_posting import JobPosting
from app.scrapers._states import parse_state
from app.scrapers.base import BaseScraper
from app.scrapers.registry import register_scraper

logger = logging.getLogger(__name__)

API_BASE = "https://api.schoolspring.com/api"
PAGE_SIZE = 100  # API accepts up to 100 per page
MAX_PAGES = 60  # safety cap (~6,000 jobs); largest TX tenant today returns ~471
DETAIL_RATE_LIMIT_S = 0.05  # 50ms between detail fetches; ~20 req/s ceiling
HTTP_TIMEOUT = 30


@register_scraper("schoolspring")
class SchoolSpringScraper(BaseScraper):

    def scrape(self) -> list[dict]:
        host = urlparse(self.source.base_url).netloc
        if not host:
            logger.warning(f"[schoolspring/{self.source.slug}] base_url has no host: {self.source.base_url!r}")
            return []

        with httpx.Client(timeout=HTTP_TIMEOUT, headers={"Accept": "application/json"}) as client:
            # 1. Pull all listings.
            listings = list(self._iter_listings(client, host))
            if not listings:
                logger.info(f"[schoolspring/{self.source.slug}] API returned 0 listings (deprovisioned tenant?)")
                return []

            logger.info(f"[schoolspring/{self.source.slug}] API listed {len(listings)} jobs")

            # 2. Look up existing rows by external_id (jobId) so we only fetch
            #    detail for NEW jobs. Existing rows already have application_url stored.
            existing_url_by_id = self._existing_apply_urls(listings)

            # 3. For each listing, attach an application_url. New jobs → fetch detail.
            results: list[dict] = []
            new_count = 0
            detail_failures = 0
            for listing in listings:
                job_id_int = listing.get("jobId")
                if not job_id_int:
                    continue
                job_id = str(job_id_int)

                apply_url = existing_url_by_id.get(job_id)
                description = None
                if not apply_url:
                    new_count += 1
                    try:
                        detail = self._fetch_detail(client, host, job_id_int)
                    except Exception as e:
                        logger.debug(f"[schoolspring/{self.source.slug}] detail fetch failed jobId={job_id}: {e}")
                        detail = None
                        detail_failures += 1
                    if detail:
                        apply_url = detail.get("infoURL") or self._fallback_url(host, job_id)
                        description = detail.get("jobDescription")
                    else:
                        apply_url = self._fallback_url(host, job_id)
                    time.sleep(DETAIL_RATE_LIMIT_S)

                results.append({
                    "jobId": job_id_int,
                    "title": listing.get("title"),
                    "employer": listing.get("employer"),
                    "location": listing.get("location"),
                    "displayDate": listing.get("displayDate"),
                    "applicationUrl": apply_url,
                    "description": description,
                })

            logger.info(
                f"[schoolspring/{self.source.slug}] returning {len(results)} jobs "
                f"({new_count} new detail-fetched, {detail_failures} detail failures)"
            )
            return results

    # --- helpers ---

    def _iter_listings(self, client: httpx.Client, host: str) -> Iterator[dict]:
        """Yield all listing dicts via paginated API. Stops on empty page or short page."""
        for page in range(1, MAX_PAGES + 1):
            try:
                resp = client.get(
                    f"{API_BASE}/Jobs/GetPagedJobsWithSearch",
                    params={
                        "domainName": host,
                        "keyword": "",
                        "location": "",
                        "category": "",
                        "gradelevel": "",
                        "jobtype": "",
                        "organization": "",
                        "swLat": "",
                        "swLon": "",
                        "neLat": "",
                        "neLon": "",
                        "page": page,
                        "size": PAGE_SIZE,
                        "sortDateAscending": "false",
                    },
                )
                resp.raise_for_status()
                payload = resp.json()
            except (httpx.HTTPError, ValueError) as e:
                logger.warning(f"[schoolspring/{self.source.slug}] listing page {page} failed: {e}")
                return
            page_jobs = ((payload or {}).get("value") or {}).get("jobsList") or []
            if not page_jobs:
                return
            yield from page_jobs
            if len(page_jobs) < PAGE_SIZE:
                return

    def _existing_apply_urls(self, listings: list[dict]) -> dict[str, str]:
        """Pre-load application_urls for jobIds we already have in the DB.

        Lets us skip per-job detail fetches for previously-scraped jobs.
        """
        external_ids = [str(l.get("jobId")) for l in listings if l.get("jobId") is not None]
        if not external_ids:
            return {}
        rows = (
            self.db.query(JobPosting.external_id, JobPosting.application_url)
            .filter(
                JobPosting.source_id == self.source.id,
                JobPosting.external_id.in_(external_ids),
            )
            .all()
        )
        return {row.external_id: row.application_url for row in rows if row.external_id and row.application_url}

    def _fetch_detail(self, client: httpx.Client, host: str, job_id: int) -> dict | None:
        """Fetch per-job detail; returns the inner jobInfo dict or None on failure."""
        resp = client.get(f"{API_BASE}/Jobs/{job_id}", params={"domainName": host})
        resp.raise_for_status()
        payload = resp.json()
        return ((payload or {}).get("value") or {}).get("jobInfo") or None

    @staticmethod
    def _fallback_url(host: str, job_id: str) -> str:
        """If detail fetch fails / lacks infoURL, fall back to a unique synthetic URL.

        Distinct per job (uses jobId) so url_hash is unique. Not a real apply page
        but at least no longer collides with sibling jobs.
        """
        return f"https://api.schoolspring.com/api/Jobs/{job_id}?domainName={host}"

    def normalize(self, raw: dict) -> dict:
        location = raw.get("location") or ""
        city = location.split(",")[0].strip() if location else None

        posting_date = None
        d = raw.get("displayDate")
        if d:
            try:
                # API format: "2026-04-30T05:00:00"
                posting_date = datetime.fromisoformat(d.replace("Z", "+00:00"))
            except (ValueError, AttributeError):
                pass

        # Default to TX for Texas-based orgs; only override when parse_state
        # returns a real state (validated against STATE_ABBREVS).
        state = parse_state(location) or "TX"

        return {
            "title": raw.get("title") or "Unknown Position",
            "application_url": raw.get("applicationUrl"),
            "location": location or None,
            "city": city,
            "state": state,
            "campus": raw.get("employer"),  # School name maps to campus
            "external_id": str(raw.get("jobId") or ""),
            "posting_date": posting_date,
            "description": raw.get("description"),
        }
