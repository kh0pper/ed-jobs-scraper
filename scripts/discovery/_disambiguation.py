"""Helpers for verifying that a probed tenant actually belongs to the org
being probed. See probe_schoolspring.py / probe_applitrack.py for usage.

Why this exists: slug generators emit short fallbacks (`pisd`, `aisd`,
`bisd`) for districts whose names share initials. Many different orgs
produce the same fallback slug, but each ATS tenant has exactly one
owner. Without a verification step the probe attributes a single tenant
to dozens of orgs (dry-run 2026-05-26: 55 districts all mapped to
`bisd`, 29 to `aisd`, 26 to `pisd`). This module supplies an
org-distinctive token that callers use against response bodies / JSON
fields to confirm ownership before recording a hit.
"""
from __future__ import annotations

_NAME_SUFFIXES = (
    " ISD",
    " CISD",
    " CONSOLIDATED ISD",
    " INDEPENDENT SCHOOL DISTRICT",
    " PUBLIC SCHOOLS",
    " ACADEMY",
    " CHARTER SCHOOL",
    " INC",
)


def distinctive_token(org_name: str) -> str | None:
    """Return the most identifying lowercase word in an org name, or None.

    Strips well-known suffixes ("ISD", "INDEPENDENT SCHOOL DISTRICT",
    etc.) and returns the longest remaining word. Prefers words >= 4
    chars to avoid generic two-letter abbreviations, but falls back to
    >= 3 chars for orgs like "DEL VALLE ISD" -> "valle".
    """
    base = org_name.strip().upper()
    for suffix in _NAME_SUFFIXES:
        if base.endswith(suffix):
            base = base[: -len(suffix)].strip()
            break
    # Hyphens within a word are real separators in district names like
    # CYPRESS-FAIRBANKS — treat them as whitespace for tokenization.
    parts = base.replace("-", " ").split()
    if not parts:
        return None
    candidates = [w for w in parts if len(w) >= 4] or [w for w in parts if len(w) >= 3]
    if not candidates:
        return None
    return max(candidates, key=len).lower()
