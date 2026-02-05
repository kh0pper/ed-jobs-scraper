"""Zipcode to coordinates service using Nominatim."""

import logging
from dataclasses import dataclass
from functools import lru_cache

import httpx

logger = logging.getLogger(__name__)

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"


@dataclass
class GeoLocation:
    """Geocoded location result."""

    latitude: float
    longitude: float
    display_name: str


@lru_cache(maxsize=1000)
def zipcode_to_coords(zipcode: str) -> GeoLocation | None:
    """
    Convert a 5-digit US zip code to lat/lon coordinates.

    Uses Nominatim (OpenStreetMap) with caching.
    Results are cached in-memory (up to 1000 entries).

    Args:
        zipcode: 5-digit US zip code

    Returns:
        GeoLocation with lat/lon, or None if not found
    """
    if not zipcode or len(zipcode) != 5 or not zipcode.isdigit():
        return None

    try:
        resp = httpx.get(
            NOMINATIM_URL,
            params={
                "postalcode": zipcode,
                "country": "US",
                "format": "json",
                "limit": 1,
            },
            headers={
                "User-Agent": "EdJobsScraper/1.0 (educational project)",
            },
            timeout=10,
        )
        resp.raise_for_status()
        results = resp.json()

        if results:
            result = results[0]
            return GeoLocation(
                latitude=float(result["lat"]),
                longitude=float(result["lon"]),
                display_name=result.get("display_name", f"ZIP {zipcode}"),
            )

        logger.warning(f"No results for zip code: {zipcode}")
        return None

    except Exception as e:
        logger.error(f"Zipcode lookup failed for {zipcode}: {e}")
        return None


def address_to_coords(address: str, state: str = "Texas") -> GeoLocation | None:
    """
    Convert an address or city name to coordinates.

    Uses Nominatim with state context for better accuracy.

    Args:
        address: City name, address, or place name
        state: State to scope the search (default: Texas)

    Returns:
        GeoLocation with lat/lon, or None if not found
    """
    if not address:
        return None

    try:
        query = f"{address}, {state}, USA" if state else f"{address}, USA"

        resp = httpx.get(
            NOMINATIM_URL,
            params={
                "q": query,
                "format": "json",
                "limit": 1,
            },
            headers={
                "User-Agent": "EdJobsScraper/1.0 (educational project)",
            },
            timeout=10,
        )
        resp.raise_for_status()
        results = resp.json()

        if results:
            result = results[0]
            return GeoLocation(
                latitude=float(result["lat"]),
                longitude=float(result["lon"]),
                display_name=result.get("display_name", address),
            )

        logger.warning(f"No results for address: {address}")
        return None

    except Exception as e:
        logger.error(f"Address lookup failed for {address}: {e}")
        return None


# Texas major cities for quick lookup (avoids API calls)
TEXAS_CITIES = {
    "houston": (29.7604, -95.3698),
    "dallas": (32.7767, -96.7970),
    "san antonio": (29.4241, -98.4936),
    "austin": (30.2672, -97.7431),
    "fort worth": (32.7555, -97.3308),
    "el paso": (31.7619, -106.4850),
    "arlington": (32.7357, -97.1081),
    "corpus christi": (27.8006, -97.3964),
    "plano": (33.0198, -96.6989),
    "laredo": (27.5036, -99.5075),
    "lubbock": (33.5779, -101.8552),
    "garland": (32.9126, -96.6389),
    "irving": (32.8140, -96.9489),
    "frisco": (33.1507, -96.8236),
    "mckinney": (33.1972, -96.6397),
    "amarillo": (35.2220, -101.8313),
    "grand prairie": (32.7459, -97.0001),
    "brownsville": (25.9017, -97.4975),
    "killeen": (31.1171, -97.7278),
    "pasadena": (29.6911, -95.2091),
}


def quick_city_lookup(city: str) -> tuple[float, float] | None:
    """
    Quick lookup for major Texas cities without API call.

    Returns (latitude, longitude) or None if city not in cache.
    """
    if not city:
        return None
    return TEXAS_CITIES.get(city.lower().strip())
