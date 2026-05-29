"""Seed ScrapeSource rows for known Skyward Qmlativ (Vue SPA) districts.

Confirmed 2026-05-29 to serve a stateless GetData POST API parsed by the
skyward_vue scraper. Hosting varies (iscorp.com cloud vs self-hosted), and the
tenant path differs per district, but the markup/API are identical.

Idempotent: keyed by tea_id; skips if a skyward_vue source already exists.

Run: docker compose exec -e PYTHONPATH=/app celery_worker python scripts/discovery/seed_skyward_vue_sources.py
"""
import re
import uuid

from app.models.base import SyncSessionLocal
from app.models.organization import Organization
from app.models.scrape_source import ScrapeSource
from app.models.job_posting import JobPosting  # noqa: F401  — resolve SQLAlchemy relationships
from app.models.scrape_run import ScrapeRun  # noqa: F401

# tea_id -> Skyward Vue ViewJobPostings board URL
TARGETS = {
    "043907": "https://skyward.iscorp.com/McKinneyISDTXBus/ApplicantTracking/JobBoard/ViewJobPostings",  # McKinney ISD
    "043914": "https://skyward.wylieisd.net/Business/ApplicantTracking/JobBoard/ViewJobPostings",        # Wylie ISD (Collin)
}


def main():
    db = SyncSessionLocal()
    try:
        for tea_id, url in TARGETS.items():
            org = db.query(Organization).filter(Organization.tea_id == tea_id).first()
            if not org:
                print(f"SKIP {tea_id}: org not found")
                continue

            existing = db.query(ScrapeSource).filter(
                ScrapeSource.organization_id == org.id,
                ScrapeSource.platform == "skyward_vue",
            ).first()
            if existing:
                if not existing.is_active:
                    existing.is_active = True
                    existing.base_url = url
                    db.commit()
                    print(f"REACTIVATED {org.name} | {url}")
                else:
                    print(f"EXISTS {org.name} | {existing.base_url}")
                continue

            db.add(ScrapeSource(
                id=uuid.uuid4(),
                organization_id=org.id,
                platform="skyward_vue",
                base_url=url,
                slug=re.sub(r"[^a-z0-9]+", "-", org.name.lower()).strip("-") + "-skyvue",
                is_active=True,
                discovered_by="seed_skyward_vue",
                scrape_frequency_minutes=360,
            ))
            db.commit()
            print(f"CREATED {org.name} | {url}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
