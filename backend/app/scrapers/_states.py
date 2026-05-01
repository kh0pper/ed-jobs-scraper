"""Shared US state name/abbreviation utilities for scrapers and data-quality tasks.

Single source of truth for state-parsing logic. Multiple scrapers and the
state-backfill cleanup task all need to map a location string like
'Houston, TX' or 'Cincinnati, Ohio' to a 2-letter abbreviation; before this
module they each maintained their own copies of the data + parsing function,
which drifted (some validated against the abbrev set, some didn't; some used
substring matching that mis-matched 'VIRGINIA' inside 'WEST VIRGINIA').

Use ``parse_state(text)`` for any new scraper that needs state extraction
from a free-form location string.

eightfold is intentionally NOT a consumer — its (US-XX) regex extracts the
state from an unambiguous tag and doesn't need this validation. See
``backend/app/scrapers/eightfold.py``.
"""

import re

# Full uppercase state name → 2-letter abbreviation. 50 states + DC.
STATE_NAMES: dict[str, str] = {
    "ALABAMA": "AL", "ALASKA": "AK", "ARIZONA": "AZ", "ARKANSAS": "AR", "CALIFORNIA": "CA",
    "COLORADO": "CO", "CONNECTICUT": "CT", "DELAWARE": "DE", "FLORIDA": "FL", "GEORGIA": "GA",
    "HAWAII": "HI", "IDAHO": "ID", "ILLINOIS": "IL", "INDIANA": "IN", "IOWA": "IA",
    "KANSAS": "KS", "KENTUCKY": "KY", "LOUISIANA": "LA", "MAINE": "ME", "MARYLAND": "MD",
    "MASSACHUSETTS": "MA", "MICHIGAN": "MI", "MINNESOTA": "MN", "MISSISSIPPI": "MS", "MISSOURI": "MO",
    "MONTANA": "MT", "NEBRASKA": "NE", "NEVADA": "NV", "NEW HAMPSHIRE": "NH", "NEW JERSEY": "NJ",
    "NEW MEXICO": "NM", "NEW YORK": "NY", "NORTH CAROLINA": "NC", "NORTH DAKOTA": "ND", "OHIO": "OH",
    "OKLAHOMA": "OK", "OREGON": "OR", "PENNSYLVANIA": "PA", "RHODE ISLAND": "RI", "SOUTH CAROLINA": "SC",
    "SOUTH DAKOTA": "SD", "TENNESSEE": "TN", "TEXAS": "TX", "UTAH": "UT", "VERMONT": "VT",
    "VIRGINIA": "VA", "WASHINGTON": "WA", "WEST VIRGINIA": "WV", "WISCONSIN": "WI", "WYOMING": "WY",
    "DISTRICT OF COLUMBIA": "DC",
}

STATE_ABBREVS: set[str] = set(STATE_NAMES.values())

# Sorted longest-first so multi-word names ("WEST VIRGINIA", "NEW MEXICO") win
# over their shorter substrings ("VIRGINIA", "MEXICO" — the latter not a state
# but defensive against accidental matches in other scrapers' data).
_STATE_NAMES_BY_LENGTH: list[str] = sorted(STATE_NAMES, key=len, reverse=True)


def parse_state(text: str | None) -> str | None:
    """Parse a 2-letter US state abbreviation from a location string.

    Tries (in order):
      1. Trailing 2-letter abbreviation validated against ``STATE_ABBREVS``
         ("Houston, TX" → "TX"; "Spring, St" → None because "ST" isn't a state).
      2. Full state name with word-boundary match, longest-first
         ("Cincinnati, Ohio" → "OH"; "Charleston, West Virginia" → "WV").

    Returns None if no valid state can be identified. The caller decides
    whether to default to TX (for known-Texas-only orgs) or to drop the row.
    """
    if not text:
        return None
    upper = text.strip().upper()

    # 1. Trailing 2-letter abbrev, validated.
    match = re.search(r"\b([A-Z]{2})\s*$", upper)
    if match and match.group(1) in STATE_ABBREVS:
        return match.group(1)

    # 2. Full state name match, longest-first to handle multi-word names.
    for name in _STATE_NAMES_BY_LENGTH:
        if re.search(rf"\b{re.escape(name)}\b", upper):
            return STATE_NAMES[name]

    return None
