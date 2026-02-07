"""City resolution service for job postings and organizations.

Derives city from:
1. Job location string parsing
2. Organization's city
3. County seat fallback

Usage:
    from app.services.city_resolver import resolve_city_for_job, derive_org_city

    city = resolve_city_for_job(job, org)
    city = derive_org_city(org)
"""

import json
import re
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.models.job_posting import JobPosting
    from app.models.organization import Organization

# Load county seats from JSON data file
_COUNTY_SEATS_PATH = Path(__file__).parent.parent / "data" / "texas_county_seats.json"
_county_seats: dict[str, str] | None = None
_county_seats_lower: dict[str, str] | None = None  # Case-insensitive lookup


def _normalize_county(name: str) -> str:
    """Normalize county name for matching (lowercase, no spaces)."""
    return name.lower().replace(" ", "")


def _get_county_seats() -> tuple[dict[str, str], dict[str, str]]:
    """Lazy-load county seats mapping (returns both original and normalized keyed dicts)."""
    global _county_seats, _county_seats_lower
    if _county_seats is None:
        if _COUNTY_SEATS_PATH.exists():
            with open(_COUNTY_SEATS_PATH) as f:
                _county_seats = json.load(f)
            # Build normalized lookup (lowercase, no spaces)
            # Handles "La Salle" vs "LaSalle", "De Witt" vs "DeWitt", etc.
            _county_seats_lower = {_normalize_county(k): v for k, v in _county_seats.items()}
        else:
            _county_seats = {}
            _county_seats_lower = {}
    return _county_seats, _county_seats_lower


def get_county_seat(county: str) -> str | None:
    """Get the county seat for a Texas county (case-insensitive, space-insensitive)."""
    if not county:
        return None
    # Normalize: strip "County" suffix if present, then normalize for matching
    normalized = _normalize_county(county.replace(" County", "").strip())
    _, lower_dict = _get_county_seats()
    return lower_dict.get(normalized)


def parse_city_from_location(location: str | None) -> str | None:
    """Parse city from location string.

    Handles formats:
    - "Houston, TX"
    - "Houston, Texas"
    - "123 Main St, Houston, TX 77001"
    - "Houston TX"
    """
    if not location:
        return None

    text = location.strip()

    # Pattern 1: "City, ST" or "City, State" at end
    # Matches: "Houston, TX" or "Spring, Texas"
    match = re.search(r"([A-Za-z\s]+),\s*(?:TX|Texas)(?:\s+\d{5})?$", text, re.IGNORECASE)
    if match:
        city = match.group(1).strip()
        # If city looks like a street address component, skip
        if not re.match(r"^\d+\s|^[NSEW]\s", city, re.IGNORECASE):
            return city.title()

    # Pattern 2: "Street, City, ST ZIP" - grab second-to-last component
    parts = [p.strip() for p in text.split(",")]
    if len(parts) >= 3:
        # Second-to-last should be city if last is "ST" or "ST ZIP"
        state_part = parts[-1].upper()
        if re.match(r"^(TX|TEXAS)(\s+\d{5})?$", state_part):
            city = parts[-2].strip()
            if city and not re.match(r"^\d+", city):
                return city.title()

    # Pattern 3: Simple "City TX" without comma
    match = re.search(r"^([A-Za-z\s]+)\s+TX$", text, re.IGNORECASE)
    if match:
        city = match.group(1).strip()
        if len(city) > 2:  # Avoid matching single words like "N TX"
            return city.title()

    return None


def resolve_city_for_job(job: "JobPosting", org: "Organization | None" = None) -> str | None:
    """Resolve city for a job posting using priority order.

    Priority:
    1. Parse from job's location string
    2. Inherit from organization's city
    3. Use county seat if org has county

    Returns:
        City name or None if cannot be determined
    """
    # 1. Parse from location
    if job.location:
        city = parse_city_from_location(job.location)
        if city:
            return city

    # 2. Inherit from org
    if org and org.city:
        return org.city

    # 3. County seat fallback
    if org and org.county:
        return get_county_seat(org.county)

    return None


def derive_org_city(org: "Organization") -> tuple[str | None, str | None]:
    """Derive city for an organization.

    Returns:
        Tuple of (city, source) where source is 'county_seat' or None
    """
    # Don't override geocode-derived or manually-set cities
    if org.city and org.city_source in ("geocode", "manual", "name_parse"):
        return org.city, org.city_source

    # If org already has a city from another source, don't override
    if org.city:
        return org.city, org.city_source

    # Try county seat lookup
    if org.county:
        city = get_county_seat(org.county)
        if city:
            return city, "county_seat"

    return None, None
