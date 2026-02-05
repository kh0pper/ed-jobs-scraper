"""Base scraper abstract class."""

import hashlib
import logging
import uuid
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any

from app.models.job_posting import JobPosting
from app.models.scrape_source import ScrapeSource

logger = logging.getLogger(__name__)


class BaseScraper(ABC):
    """Abstract base class for all platform scrapers.

    Subclasses must implement:
        scrape() -> list[dict]  — fetch raw job data from the platform
        normalize(raw) -> dict  — convert platform-specific fields to standard schema
    """

    def __init__(self, source: ScrapeSource, db):
        self.source = source
        self.db = db
        self.platform = source.platform

    @abstractmethod
    def scrape(self) -> list[dict]:
        """Fetch raw job listings from the platform. Returns list of raw dicts."""
        ...

    @abstractmethod
    def normalize(self, raw: dict) -> dict:
        """Normalize a raw job dict to standard schema fields.

        Must return a dict with at least:
            - title (str)
            - application_url (str)

        Optional fields:
            - location, city, state, category, raw_category, department
            - employment_type, salary_min, salary_max, salary_text
            - posting_date, closing_date, description, requirements
            - external_id, extra_data (dict)
        """
        ...

    def run(self) -> dict[str, Any]:
        """Execute the full scrape cycle: fetch, normalize, save."""
        raw_listings = self.scrape()
        logger.info(f"[{self.platform}/{self.source.slug}] Fetched {len(raw_listings)} raw listings")

        jobs_found = len(raw_listings)
        jobs_new = 0
        jobs_updated = 0

        for raw in raw_listings:
            try:
                normalized = self.normalize(raw)
                result = self._save_posting(normalized)
                if result == "new":
                    jobs_new += 1
                elif result == "updated":
                    jobs_updated += 1
            except Exception as e:
                logger.warning(f"[{self.platform}/{self.source.slug}] Failed to process listing: {e}")

        return {"jobs_found": jobs_found, "jobs_new": jobs_new, "jobs_updated": jobs_updated}

    def _save_posting(self, data: dict) -> str:
        """Save or update a job posting. Returns 'new', 'updated', or 'existing'."""
        now = datetime.now(timezone.utc)
        url_hash = self._hash_url(data["application_url"])
        content_hash = self._hash_content(data.get("title", ""), data.get("description", ""))

        existing = self.db.query(JobPosting).filter(JobPosting.url_hash == url_hash).first()

        if existing:
            existing.last_seen_at = now
            if existing.content_hash != content_hash:
                # Content changed — update fields
                for key in ("title", "location", "city", "state", "category", "raw_category",
                            "department", "employment_type", "salary_min", "salary_max",
                            "salary_text", "closing_date", "description", "requirements"):
                    if key in data and data[key] is not None:
                        setattr(existing, key, data[key])
                existing.content_hash = content_hash
                existing.is_active = True
                self.db.commit()
                return "updated"
            else:
                existing.is_active = True
                self.db.commit()
                return "existing"
        else:
            posting = JobPosting(
                id=uuid.uuid4(),
                organization_id=self.source.organization_id,
                source_id=self.source.id,
                url_hash=url_hash,
                content_hash=content_hash,
                title=data["title"],
                application_url=data["application_url"],
                location=data.get("location"),
                city=data.get("city"),
                state=data.get("state"),
                category=data.get("category"),
                raw_category=data.get("raw_category"),
                department=data.get("department"),
                employment_type=data.get("employment_type"),
                salary_min=data.get("salary_min"),
                salary_max=data.get("salary_max"),
                salary_text=data.get("salary_text"),
                posting_date=data.get("posting_date"),
                closing_date=data.get("closing_date"),
                description=data.get("description"),
                requirements=data.get("requirements"),
                platform=self.platform,
                external_id=data.get("external_id"),
                extra_data=data.get("extra_data", {}),
                first_seen_at=now,
                last_seen_at=now,
                is_active=True,
            )
            self.db.add(posting)
            self.db.commit()
            return "new"

    @staticmethod
    def _hash_url(url: str) -> str:
        return hashlib.sha256(url.encode()).hexdigest()

    @staticmethod
    def _hash_content(title: str, description: str) -> str:
        content = f"{title}|{description or ''}"
        return hashlib.sha256(content.encode()).hexdigest()
