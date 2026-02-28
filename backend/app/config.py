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

    # Geocoding (local Nominatim via Docker)
    census_geocoder_url: str = "https://geocoding.geo.census.gov/geocoder/locations/onelineaddress"
    nominatim_url: str = "http://nominatim:8080/search"
    nominatim_rate_limit: float = 0.1  # Local instance, no rate limit needed

    # Scraping
    default_scrape_frequency_minutes: int = 360
    scrape_timeout: int = 120
    max_browser_pages: int = 3

    # Z.ai (AI generation)
    zai_api_key: str = ""
    zai_base_url: str = "https://api.z.ai/api/coding/paas/v4"
    zai_model_routine: str = "glm-4.5v"
    zai_model_complex: str = "glm-4.7"

    # Google Docs/Drive
    google_credentials_file: str = "/app/config/google_credentials.json"

    # Email (Gmail SMTP)
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""

    # Easy Apply pipeline
    apply_pdf_dir: str = "/app/data/pdfs"
    apply_screenshot_dir: str = "/app/data/screenshots"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


@lru_cache
def get_settings() -> Settings:
    return Settings()
