"""Disposition collision-duplicate scrape_sources.

A "collision" is a base_url shared by 2+ active scrape_sources belonging
to different organizations. These were created by the Stage 0/1 probe
runs when multiple orgs generated the same bare-acronym slug
(`pisd`, `aisd`, `wisd`, ...). Each ATS tenant has exactly one owner;
only one of the colliding orgs is correct.

This script scores each candidate org against the tenant's actual
content (HTML body for applitrack, jobs JSON for schoolspring) using
three signals — org.city, org.county, and the org name's distinctive
token — and proposes deactivating the losers. Tie-breaking favors orgs
with stronger evidence; ties are surfaced for human review (no action).

Usage:
    docker compose exec backend python -m scripts.discovery.disposition_collisions --dry-run
    docker compose exec backend python -m scripts.discovery.disposition_collisions
"""
import argparse
import logging
import re
from collections import defaultdict
from typing import Any

import httpx

from app.models.base import SyncSessionLocal
from app.models.organization import Organization
from app.models.scrape_source import ScrapeSource
from app.models.job_posting import JobPosting  # noqa: F401
from app.models.scrape_run import ScrapeRun  # noqa: F401
from scripts.discovery._disambiguation import distinctive_token

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def fetch_applitrack_body(base_url: str, client: httpx.Client) -> str:
    try:
        resp = client.get(base_url, timeout=20, follow_redirects=True)
        return resp.text.lower() if resp.status_code == 200 else ""
    except (httpx.HTTPError, httpx.TimeoutException):
        return ""


def fetch_schoolspring_haystack(base_url: str, client: httpx.Client) -> str:
    # base_url is like https://<slug>.schoolspring.com/
    host = base_url.replace("https://", "").replace("http://", "").strip("/")
    api = (
        "https://api.schoolspring.com/api/Jobs/GetPagedJobsWithSearch"
        f"?domainName={host}&page=1&size=100"
    )
    try:
        resp = client.get(api, timeout=20)
        if resp.status_code != 200:
            return ""
        jl = ((resp.json() or {}).get("value") or {}).get("jobsList") or []
        return " ".join(
            (j.get("employer") or "") + " " + (j.get("title") or "") + " " + (j.get("location") or "")
            for j in jl
        ).lower()
    except (httpx.HTTPError, httpx.TimeoutException, ValueError):
        return ""


def _wb_count(haystack: str, phrase: str) -> int:
    """Word-boundary-aware count of `phrase` in `haystack` (already lowercased).

    Substring counting wrongly inflates short tokens — "post" matches
    inside "posting", "posted", "position", "post-secondary", etc., which
    in turn makes POST ISD beat PLANO ISD when scoring the `pisd`
    tenant. Word-boundary matching avoids that.

    Multi-word phrases (e.g. "highland park", "mount calm") collapse
    runs of whitespace to a single space-tolerant pattern.
    """
    if not phrase:
        return 0
    inner = r"\s+".join(re.escape(w) for w in phrase.split())
    return len(re.findall(rf"\b{inner}\b", haystack))


def score_org(haystack: str, org: Organization) -> tuple[int, dict[str, int]]:
    """Score how strongly an org's identity appears in tenant content."""
    if not haystack:
        return 0, {}
    pieces = {}
    # Distinctive name token (e.g., 'plano', 'wells')
    tok = distinctive_token(org.name)
    if tok:
        pieces["token"] = _wb_count(haystack, tok)
    # City: typically the most decisive signal when present
    if org.city:
        pieces["city"] = _wb_count(haystack, org.city.lower())
    # County: weaker but useful
    if org.county:
        pieces["county"] = _wb_count(haystack, org.county.lower())
    # Weighted total — city dominates because it's the most location-specific
    total = (
        pieces.get("token", 0) * 1
        + pieces.get("city", 0) * 3
        + pieces.get("county", 0) * 2
    )
    return total, pieces


def find_collisions(db) -> list[dict[str, Any]]:
    """Return groups of active sources sharing a base_url."""
    rows = (
        db.query(ScrapeSource, Organization)
        .join(Organization, Organization.id == ScrapeSource.organization_id)
        .filter(
            ScrapeSource.is_active.is_(True),
            ScrapeSource.platform.in_(("applitrack", "schoolspring")),
        )
        .all()
    )
    groups: dict[tuple[str, str], list[tuple[ScrapeSource, Organization]]] = defaultdict(list)
    for src, org in rows:
        groups[(src.platform, src.base_url)].append((src, org))
    return [
        {"platform": k[0], "base_url": k[1], "members": v}
        for k, v in groups.items()
        if len(v) > 1
    ]


def disposition(dry_run: bool = False):
    db = SyncSessionLocal()
    client = httpx.Client(
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/121.0.0.0 Safari/537.36",
        },
    )
    try:
        collisions = find_collisions(db)
        logger.info("Found %d collision groups across applitrack+schoolspring", len(collisions))
        if not collisions:
            return

        kept = 0
        deactivated = 0
        unresolved = 0

        for c in collisions:
            base = c["base_url"]
            platform = c["platform"]
            members = c["members"]

            if platform == "applitrack":
                haystack = fetch_applitrack_body(base, client)
            else:
                haystack = fetch_schoolspring_haystack(base, client)

            scored = []
            for src, org in members:
                s, pieces = score_org(haystack, org)
                scored.append((s, pieces, src, org))
            scored.sort(key=lambda x: x[0], reverse=True)

            logger.info("")
            logger.info("=== %s  %s  (%d candidates) ===", platform, base, len(members))
            for s, pieces, src, org in scored:
                logger.info(
                    "  score=%-3d  %-35s  city=%s  county=%s  pieces=%s",
                    s, org.name, org.city, org.county, pieces,
                )

            top = scored[0]
            tie = len(scored) > 1 and scored[1][0] == top[0]
            if top[0] == 0 or tie:
                logger.info("  -> UNRESOLVED (zero or tied scores); leaving all active for manual review")
                unresolved += 1
                continue

            winner = top
            logger.info("  -> KEEP %s (score %d)", winner[3].name, winner[0])
            kept += 1
            for s, pieces, src, org in scored[1:]:
                logger.info("  -> DEACTIVATE %s (score %d)", org.name, s)
                if not dry_run:
                    src.is_active = False
                    org.platform_status = "unmapped"  # mark for re-discovery
                    deactivated += 1
            if not dry_run:
                db.commit()

        logger.info("")
        logger.info("Summary: kept=%d  deactivated=%d  unresolved=%d", kept, deactivated, unresolved)
        if dry_run:
            logger.info("(Dry run — no changes saved)")
    finally:
        client.close()
        db.close()


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Disposition collision-duplicate scrape_sources")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()
    disposition(dry_run=args.dry_run)
