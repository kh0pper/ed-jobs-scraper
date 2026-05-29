"""Seed ScrapeSource rows for the known Frontline ERP / TEAMS districts.

These three were confirmed (2026-05-29) to serve a fully server-rendered
``EntryPointBrowseJobPostingsAction.do`` board parsed by the frontline_erp
scraper. Hosting differs (cloud vs self-hosted teams.*) but markup is identical.

Idempotent: keyed by tea_id; skips if a frontline_erp source already exists.

Run: docker compose exec celery_worker python scripts/discovery/seed_frontline_sources.py
"""
import re
import uuid

from app.models.base import SyncSessionLocal
from app.models.organization import Organization
from app.models.scrape_source import ScrapeSource
from app.models.job_posting import JobPosting  # noqa: F401  — resolve SQLAlchemy relationships
from app.models.scrape_run import ScrapeRun  # noqa: F401

# tea_id -> Frontline browse-board URL
TARGETS = {
    "071902": "https://elpasoisd.erp.frontlineeducation.com/submission/EntryPointBrowseJobPostingsAction.do?applicantType=external",  # El Paso ISD
    "101911": "https://teams.gccisd.net/submission/EntryPointBrowseJobPostingsAction.do?applicantType=external",                      # Goose Creek CISD
    "212905": "https://tylerisd.erp.frontlineeducation.com/submission/EntryPointBrowseJobPostingsAction.do?applicantType=external",   # Tyler ISD
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
                ScrapeSource.platform == "frontline_erp",
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
                platform="frontline_erp",
                base_url=url,
                slug=re.sub(r"[^a-z0-9]+", "-", org.name.lower()).strip("-"),
                is_active=True,
                discovered_by="seed_frontline",
                scrape_frequency_minutes=360,
            ))
            db.commit()
            print(f"CREATED {org.name} | {url}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
