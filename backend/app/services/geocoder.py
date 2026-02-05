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


@dataclass
class GeoResult:
    """Result from geocoding operation."""

    latitude: float
    longitude: float
    display_name: str
    confidence: float  # 0-1 based on importance


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
        self.user_agent = "TexasEdJobsScraper/1.0 (https://github.com/kh0pp/ed-jobs-scraper)"

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
                return GeoResult(
                    latitude=float(result["lat"]),
                    longitude=float(result["lon"]),
                    display_name=result.get("display_name", ""),
                    confidence=min(float(result.get("importance", 0.5)), 1.0),
                )

        except httpx.HTTPError as e:
            logger.error(f"Geocoding HTTP error for '{search_query}': {e}")
            return None
        except (KeyError, ValueError) as e:
            logger.error(f"Geocoding parse error for '{search_query}': {e}")
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
                return GeoResult(
                    latitude=float(result["lat"]),
                    longitude=float(result["lon"]),
                    display_name=result.get("display_name", ""),
                    confidence=min(float(result.get("importance", 0.5)), 1.0),
                )

        except httpx.HTTPError as e:
            logger.error(f"Geocoding HTTP error for '{search_query}': {e}")
            return None
        except (KeyError, ValueError) as e:
            logger.error(f"Geocoding parse error for '{search_query}': {e}")
            return None


def geocode_organization(
    name: str,
    city: Optional[str] = None,
    county: Optional[str] = None,
) -> Optional[GeoResult]:
    """
    Geocode a Texas school district or organization.

    Args:
        name: Organization name (e.g., "Houston ISD")
        city: Optional city hint
        county: Optional county hint

    Returns:
        GeoResult if found, None otherwise
    """
    geocoder = Geocoder(rate_limit=settings.nominatim_rate_limit)

    # Try with name directly first
    result = geocoder.geocode_sync(name, city=city)
    if result:
        return result

    # Try with county if available
    if county:
        result = geocoder.geocode_sync(f"{name}, {county} County")
        if result:
            return result

    return None


def geocode_job_location(
    location: Optional[str],
    city: Optional[str] = None,
    org_name: Optional[str] = None,
) -> Optional[GeoResult]:
    """
    Geocode a job posting location.

    Args:
        location: Location string from job posting
        city: City if known
        org_name: Organization name for context

    Returns:
        GeoResult if found, None otherwise
    """
    geocoder = Geocoder(rate_limit=settings.nominatim_rate_limit)

    # Try location directly
    if location:
        result = geocoder.geocode_sync(location, city=city)
        if result:
            return result

    # Fall back to city
    if city:
        result = geocoder.geocode_sync(city)
        if result:
            return result

    return None
