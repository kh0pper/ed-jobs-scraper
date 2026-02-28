"""Digest builder — assembles weekly email content.

Queries new jobs since last digest, groups by category, applies
recommendation scoring for personalized ordering.
"""

import logging
from datetime import datetime, timezone, timedelta

from sqlalchemy import select, func, and_
from sqlalchemy.orm import Session

from app.models.job_posting import JobPosting
from app.models.organization import Organization
from app.models.application import Application

logger = logging.getLogger(__name__)


def build_digest(
    session: Session,
    user_id,
    preferences,
    app_url: str = "http://localhost:8002",
) -> dict:
    """Build digest context for email template and /for-you page.

    Args:
        session: Sync SQLAlchemy session
        user_id: User UUID
        preferences: DigestPreference ORM object
        app_url: Base URL for links

    Returns:
        dict with template context:
            - new_jobs: list of job dicts grouped by category
            - total_new: count of new jobs
            - categories: dict of category → count
            - date_range: (start_date, end_date)
    """
    # Determine date range
    since = preferences.last_job_seen_at
    if not since:
        since = datetime.now(timezone.utc) - timedelta(days=7)

    now = datetime.now(timezone.utc)

    # Build query filters
    filters = [
        JobPosting.is_active == True,
        JobPosting.first_seen_at >= since,
    ]

    if preferences.categories:
        filters.append(JobPosting.category.in_(preferences.categories))

    if preferences.regions:
        filters.append(Organization.esc_region.in_([str(r) for r in preferences.regions]))

    # Query new jobs with org info
    query = (
        select(
            JobPosting.id,
            JobPosting.title,
            JobPosting.application_url,
            JobPosting.category,
            JobPosting.city,
            JobPosting.platform,
            JobPosting.posting_date,
            JobPosting.first_seen_at,
            Organization.name.label("org_name"),
            Organization.id.label("org_id"),
        )
        .outerjoin(Organization, JobPosting.organization_id == Organization.id)
        .where(and_(*filters))
        .order_by(JobPosting.first_seen_at.desc())
        .limit(preferences.max_jobs)
    )

    result = session.execute(query)
    jobs = []
    categories = {}

    for row in result.mappings():
        job = {
            "id": str(row["id"]),
            "title": row["title"],
            "application_url": row["application_url"],
            "category": row["category"] or "Other",
            "city": row["city"] or "",
            "platform": row["platform"],
            "posting_date": row["posting_date"],
            "first_seen_at": row["first_seen_at"],
            "org_name": row["org_name"] or "Unknown",
            "org_id": str(row["org_id"]) if row["org_id"] else None,
            "easy_apply_url": f"{app_url}/apply/{row['id']}",
        }
        jobs.append(job)

        cat = job["category"]
        categories[cat] = categories.get(cat, 0) + 1

    # Count total new (without limit)
    count_query = (
        select(func.count(JobPosting.id))
        .outerjoin(Organization, JobPosting.organization_id == Organization.id)
        .where(and_(*filters))
    )
    total_new = session.execute(count_query).scalar() or 0

    # Get user's application statuses
    app_result = session.execute(
        select(Application.job_posting_id, Application.status)
        .where(Application.user_id == user_id)
    )
    application_statuses = {str(row[0]): row[1] for row in app_result}

    # Group jobs by category
    by_category = {}
    for job in jobs:
        cat = job["category"]
        if cat not in by_category:
            by_category[cat] = []
        job["application_status"] = application_statuses.get(job["id"])
        by_category[cat].append(job)

    return {
        "jobs_by_category": by_category,
        "all_jobs": jobs,
        "total_new": total_new,
        "categories": categories,
        "date_range": (since, now),
        "app_url": app_url,
    }
