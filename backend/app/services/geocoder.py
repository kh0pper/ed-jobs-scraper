"""Geocoding service using Nominatim (OpenStreetMap)."""

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Optional

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


# Texas bounding box for sanity-checking geocode results
TEXAS_LAT_MIN, TEXAS_LAT_MAX = 25.8, 36.5
TEXAS_LON_MIN, TEXAS_LON_MAX = -106.6, -93.5


def _extract_city_from_address(address: dict) -> str | None:
    """Extract city name from Nominatim address details."""
    return (
        address.get("city")
        or address.get("town")
        or address.get("village")
        or address.get("hamlet")
        or address.get("municipality")
    )


def _is_in_texas(lat: float, lon: float) -> bool:
    """Check if coordinates fall within Texas bounding box."""
    return TEXAS_LAT_MIN <= lat <= TEXAS_LAT_MAX and TEXAS_LON_MIN <= lon <= TEXAS_LON_MAX


@dataclass
class GeoResult:
    """Result from geocoding operation."""

    latitude: float
    longitude: float
    display_name: str
    confidence: float  # 0-1 based on importance
    city: str | None = None  # Extracted from addressdetails


class Geocoder:
    """
    Rate-limited geocoder using Nominatim API.

    Nominatim requires:
    - Max 1 request per second
    - User-Agent header identifying the application
    """

    def __init__(self, rate_limit: float = 1.0):
        """
        Initialize geocoder.

        Args:
            rate_limit: Minimum seconds between requests (default 1.0)
        """
        self.rate_limit = rate_limit
        self.last_request_time = 0.0
        self.base_url = settings.nominatim_url
        self.user_agent = "TexasEdJobsScraper/1.0 (mailto:kh0pper@gmail.com; https://github.com/kh0pper/ed-jobs-scraper)"

    def _wait_for_rate_limit(self) -> None:
        """Block until rate limit allows next request."""
        elapsed = time.time() - self.last_request_time
        if elapsed < self.rate_limit:
            time.sleep(self.rate_limit - elapsed)
        self.last_request_time = time.time()

    async def _async_wait_for_rate_limit(self) -> None:
        """Async version of rate limit wait."""
        elapsed = time.time() - self.last_request_time
        if elapsed < self.rate_limit:
            await asyncio.sleep(self.rate_limit - elapsed)
        self.last_request_time = time.time()

    def geocode_sync(
        self,
        query: str,
        city: Optional[str] = None,
        state: str = "Texas",
        country: str = "USA",
    ) -> Optional[GeoResult]:
        """
        Geocode an address synchronously.

        Args:
            query: Address or location string
            city: Optional city name to improve accuracy
            state: State name (default: Texas)
            country: Country name (default: USA)

        Returns:
            GeoResult if found, None otherwise
        """
        self._wait_for_rate_limit()

        # Build search query
        parts = [query]
        if city:
            parts.append(city)
        parts.extend([state, country])
        search_query = ", ".join(filter(None, parts))

        try:
            with httpx.Client(timeout=30) as client:
                response = client.get(
                    self.base_url,
                    params={
                        "q": search_query,
                        "format": "json",
                        "limit": 1,
                        "addressdetails": 1,
                    },
                    headers={"User-Agent": self.user_agent},
                )
                response.raise_for_status()

                results = response.json()
                if not results:
                    logger.debug(f"No geocoding results for: {search_query}")
                    return None

                result = results[0]
                lat = float(result["lat"])
                lon = float(result["lon"])

                if not _is_in_texas(lat, lon):
                    logger.debug(f"Geocoding result outside Texas bounds for '{search_query}': {lat}, {lon}")
                    return None

                address = result.get("address", {})
                return GeoResult(
                    latitude=lat,
                    longitude=lon,
                    display_name=result.get("display_name", ""),
                    confidence=min(float(result.get("importance", 0.5)), 1.0),
                    city=_extract_city_from_address(address),
                )

        except httpx.HTTPError as e:
            logger.error(f"Geocoding HTTP error for '{search_query}': {e}")
            return None
        except (KeyError, ValueError) as e:
            logger.error(f"Geocoding parse error for '{search_query}': {e}")
            return None

    def geocode_city_sync(
        self, city: str, state: str = "Texas", country: str = "USA"
    ) -> Optional[GeoResult]:
        """
        Geocode a city name using structured search parameters.

        Uses Nominatim's structured query (city/state/country as separate params)
        instead of free-text search, which avoids county name collisions
        (e.g. "Austin" matching Austin County instead of City of Austin).
        """
        self._wait_for_rate_limit()

        try:
            with httpx.Client(timeout=30) as client:
                response = client.get(
                    self.base_url,
                    params={
                        "city": city,
                        "state": state,
                        "country": country,
                        "format": "json",
                        "limit": 1,
                        "addressdetails": 1,
                    },
                    headers={"User-Agent": self.user_agent},
                )
                response.raise_for_status()

                results = response.json()
                if not results:
                    logger.debug(f"No geocoding results for city: {city}")
                    return None

                result = results[0]
                lat = float(result["lat"])
                lon = float(result["lon"])

                if not _is_in_texas(lat, lon):
                    logger.debug(f"Geocoding result outside Texas bounds for city '{city}': {lat}, {lon}")
                    return None

                address = result.get("address", {})
                return GeoResult(
                    latitude=lat,
                    longitude=lon,
                    display_name=result.get("display_name", ""),
                    confidence=min(float(result.get("importance", 0.5)), 1.0),
                    city=_extract_city_from_address(address),
                )

        except httpx.HTTPError as e:
            logger.error(f"Geocoding HTTP error for city '{city}': {e}")
            return None
        except (KeyError, ValueError) as e:
            logger.error(f"Geocoding parse error for city '{city}': {e}")
            return None

    async def geocode_async(
        self,
        query: str,
        city: Optional[str] = None,
        state: str = "Texas",
        country: str = "USA",
    ) -> Optional[GeoResult]:
        """
        Geocode an address asynchronously.

        Args:
            query: Address or location string
            city: Optional city name to improve accuracy
            state: State name (default: Texas)
            country: Country name (default: USA)

        Returns:
            GeoResult if found, None otherwise
        """
        await self._async_wait_for_rate_limit()

        # Build search query
        parts = [query]
        if city:
            parts.append(city)
        parts.extend([state, country])
        search_query = ", ".join(filter(None, parts))

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.get(
                    self.base_url,
                    params={
                        "q": search_query,
                        "format": "json",
                        "limit": 1,
                        "addressdetails": 1,
                    },
                    headers={"User-Agent": self.user_agent},
                )
                response.raise_for_status()

                results = response.json()
                if not results:
                    logger.debug(f"No geocoding results for: {search_query}")
                    return None

                result = results[0]
                lat = float(result["lat"])
                lon = float(result["lon"])

                if not _is_in_texas(lat, lon):
                    logger.debug(f"Geocoding result outside Texas bounds for '{search_query}': {lat}, {lon}")
                    return None

                address = result.get("address", {})
                return GeoResult(
                    latitude=lat,
                    longitude=lon,
                    display_name=result.get("display_name", ""),
                    confidence=min(float(result.get("importance", 0.5)), 1.0),
                    city=_extract_city_from_address(address),
                )

        except httpx.HTTPError as e:
            logger.error(f"Geocoding HTTP error for '{search_query}': {e}")
            return None
        except (KeyError, ValueError) as e:
            logger.error(f"Geocoding parse error for '{search_query}': {e}")
            return None
