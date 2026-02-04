"""Scraper registry — maps platform names to scraper classes."""

import logging
from typing import Type

from app.scrapers.base import BaseScraper

logger = logging.getLogger(__name__)

# Platform name -> scraper class mapping
_REGISTRY: dict[str, Type[BaseScraper]] = {}


def register_scraper(platform: str):
    """Decorator to register a scraper class for a platform."""
    def decorator(cls: Type[BaseScraper]):
        _REGISTRY[platform] = cls
        logger.debug(f"Registered scraper for platform: {platform}")
        return cls
    return decorator


def get_scraper_class(platform: str) -> Type[BaseScraper] | None:
    """Look up the scraper class for a given platform."""
    return _REGISTRY.get(platform)


def list_platforms() -> list[str]:
    """List all registered platforms."""
    return list(_REGISTRY.keys())
