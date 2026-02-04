"""Application configuration from environment variables."""

from functools import lru_cache
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Application
    app_name: str = "Texas Ed Jobs Scraper"
    debug: bool = False
    secret_key: str = "change-me-in-production"

    # Database
    database_url: str = "postgresql+asyncpg://edjobs_user:edjobs_secure_2026@edjobs_postgres:5432/edjobs"

    # Redis
    redis_url: str = "redis://edjobs_redis:6379/0"

    # TEA Data
    tea_db_path: str = "/app/data/tea_data.db"

    # Geocoding
    census_geocoder_url: str = "https://geocoding.geo.census.gov/geocoder/locations/onelineaddress"
    nominatim_url: str = "https://nominatim.openstreetmap.org/search"
    nominatim_rate_limit: float = 0.5

    # Scraping
    default_scrape_frequency_minutes: int = 360
    scrape_timeout: int = 120
    max_browser_pages: int = 3

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


@lru_cache
def get_settings() -> Settings:
    return Settings()
