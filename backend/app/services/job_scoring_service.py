"""Job scoring service — personalized recommendations via SQL-based JSONB scoring."""

from uuid import UUID

from sqlalchemy import select, func, text, case
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.job_posting import JobPosting
from app.models.organization import Organization
from app.models.user_interest_profile import UserInterestProfile
from app.models.user_interaction import UserInteraction

COLD_START_THRESHOLD = 10  # Active interactions needed before personalized scoring


async def get_recommendations(
    db: AsyncSession,
    user_id: UUID,
    limit: int = 20,
    offset: int = 0,
) -> tuple[list[dict], int]:
    """Get recommended jobs for a user.

    Returns (jobs_list, total_count).
    Uses personalized JSONB scoring when user has enough interactions,
    falls back to popularity + recency for cold start.
    """
    # Count active interactions (not views)
    active_count_result = await db.execute(
        select(func.count(UserInteraction.id))
        .where(
            UserInteraction.user_id == user_id,
            UserInteraction.interaction_type.in_(["save", "thumbs_up", "thumbs_down", "apply_click"]),
        )
    )
    active_count = active_count_result.scalar() or 0

    if active_count >= COLD_START_THRESHOLD:
        return await _personalized_query(db, user_id, limit, offset)
    else:
        return await _cold_start_query(db, limit, offset)


async def _personalized_query(
    db: AsyncSession,
    user_id: UUID,
    limit: int,
    offset: int,
) -> tuple[list[dict], int]:
    """Personalized scoring using JSONB dimension lookups in SQL."""
    # Get the user's profile
    profile_result = await db.execute(
        select(UserInterestProfile).where(UserInterestProfile.user_id == user_id)
    )
    profile = profile_result.scalar_one_or_none()

    if not profile:
        return await _cold_start_query(db, limit, offset)

    # Build SQL scoring expression using JSONB ->> operator
    # score = category_match * 0.35 + city_match * 0.30 + region_match * 0.15
    #       + org_type_match * 0.10 + recency * 0.10
    #
    # We use text() for the JSONB lookups since SQLAlchemy's JSONB operators
    # are cumbersome for dynamic key lookups.

    score_expr = text("""
        (
            COALESCE((:cat_scores ::jsonb ->> job_postings.category)::float, 0.5) * 0.35 +
            COALESCE((:city_scores ::jsonb ->> job_postings.city)::float, 0.5) * 0.30 +
            COALESCE((:region_scores ::jsonb ->> organizations.esc_region::text)::float, 0.5) * 0.15 +
            COALESCE((:org_type_scores ::jsonb ->> organizations.org_type)::float, 0.5) * 0.10 +
            POWER(0.5, EXTRACT(EPOCH FROM (NOW() - job_postings.first_seen_at)) / 604800.0) * 0.10
        )
    """)

    import json
    params = {
        "cat_scores": json.dumps(profile.category_scores or {}),
        "city_scores": json.dumps(profile.city_scores or {}),
        "region_scores": json.dumps(profile.region_scores or {}),
        "org_type_scores": json.dumps(profile.org_type_scores or {}),
    }

    # Count total active jobs
    count_result = await db.execute(
        select(func.count(JobPosting.id)).where(JobPosting.is_active == True)
    )
    total = count_result.scalar() or 0

    # Main query with scoring
    query = (
        select(
            JobPosting.id,
            JobPosting.title,
            JobPosting.application_url,
            JobPosting.category,
            JobPosting.city,
            JobPosting.platform,
            JobPosting.latitude,
            JobPosting.longitude,
            JobPosting.posting_date,
            JobPosting.first_seen_at,
            Organization.name.label("org_name"),
            Organization.id.label("org_id"),
            score_expr.label("score"),
        )
        .outerjoin(Organization, JobPosting.organization_id == Organization.id)
        .where(JobPosting.is_active == True)
        .order_by(text("score DESC"))
        .offset(offset)
        .limit(limit)
    )

    result = await db.execute(query, params)

    jobs = []
    for row in result.mappings():
        jobs.append({
            "id": row["id"],
            "title": row["title"],
            "application_url": row["application_url"],
            "org_name": row["org_name"],
            "category": row["category"],
            "city": row["city"],
            "platform": row["platform"],
            "latitude": row["latitude"],
            "longitude": row["longitude"],
            "posting_date": row["posting_date"],
            "score": float(row["score"]) if row["score"] else 0,
        })

    return jobs, total


async def _cold_start_query(
    db: AsyncSession,
    limit: int,
    offset: int,
) -> tuple[list[dict], int]:
    """Cold start fallback: popularity + recency scoring.

    cold_start_score = 0.6 * popularity_score + 0.4 * recency
    Popularity is computed via subquery counting interactions.
    """
    # Count total
    count_result = await db.execute(
        select(func.count(JobPosting.id)).where(JobPosting.is_active == True)
    )
    total = count_result.scalar() or 0

    # Popularity subquery — counts weighted interactions per job
    popularity_sub = (
        select(
            UserInteraction.job_posting_id,
            (
                func.count(case((UserInteraction.interaction_type == "save", 1))) * 0.4
                + func.count(case((UserInteraction.interaction_type == "apply_click", 1))) * 0.3
                + func.count(case((UserInteraction.interaction_type == "thumbs_up", 1))) * 0.2
                + func.count(case((UserInteraction.interaction_type == "view", 1))) * 0.1
            ).label("pop_score"),
        )
        .group_by(UserInteraction.job_posting_id)
        .subquery()
    )

    # Recency: 7-day half-life
    recency_expr = text("POWER(0.5, EXTRACT(EPOCH FROM (NOW() - job_postings.first_seen_at)) / 604800.0)")

    # Combined cold start score
    # Normalize popularity to [0, 1] — use GREATEST to avoid div by zero
    cold_score = text("""
        (COALESCE(pop_sub.pop_score, 0) / GREATEST((SELECT MAX(pop_sub2.pop_score) FROM (
            SELECT job_posting_id,
                   COUNT(*) FILTER (WHERE interaction_type = 'save') * 0.4
                 + COUNT(*) FILTER (WHERE interaction_type = 'apply_click') * 0.3
                 + COUNT(*) FILTER (WHERE interaction_type = 'thumbs_up') * 0.2
                 + COUNT(*) FILTER (WHERE interaction_type = 'view') * 0.1 AS pop_score
            FROM user_interactions GROUP BY job_posting_id
        ) pop_sub2), 1.0)) * 0.6
        + POWER(0.5, EXTRACT(EPOCH FROM (NOW() - job_postings.first_seen_at)) / 604800.0) * 0.4
    """)

    query = (
        select(
            JobPosting.id,
            JobPosting.title,
            JobPosting.application_url,
            JobPosting.category,
            JobPosting.city,
            JobPosting.platform,
            JobPosting.latitude,
            JobPosting.longitude,
            JobPosting.posting_date,
            JobPosting.first_seen_at,
            Organization.name.label("org_name"),
            Organization.id.label("org_id"),
        )
        .outerjoin(Organization, JobPosting.organization_id == Organization.id)
        .outerjoin(popularity_sub, JobPosting.id == popularity_sub.c.job_posting_id)
        .where(JobPosting.is_active == True)
        .order_by(JobPosting.first_seen_at.desc())  # Simple fallback: newest first
        .offset(offset)
        .limit(limit)
    )

    result = await db.execute(query)

    jobs = []
    for row in result.mappings():
        jobs.append({
            "id": row["id"],
            "title": row["title"],
            "application_url": row["application_url"],
            "org_name": row["org_name"],
            "category": row["category"],
            "city": row["city"],
            "platform": row["platform"],
            "latitude": row["latitude"],
            "longitude": row["longitude"],
            "posting_date": row["posting_date"],
        })

    return jobs, total
