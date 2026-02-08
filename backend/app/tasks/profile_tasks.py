"""Celery tasks for user interest profile updates."""

import logging
from datetime import datetime, timezone, timedelta

from sqlalchemy import select, func

from app.tasks.celery_app import celery_app
from app.models.base import SyncSessionLocal

# Import ALL models to ensure relationships resolve (same pattern as scrape_tasks)
from app.models.organization import Organization  # noqa: F401
from app.models.job_posting import JobPosting  # noqa: F401
from app.models.scrape_source import ScrapeSource  # noqa: F401
from app.models.scrape_run import ScrapeRun  # noqa: F401
from app.models.user import User  # noqa: F401
from app.models.saved_job import SavedJob  # noqa: F401
from app.models.user_interaction import UserInteraction
from app.models.user_interest_profile import UserInterestProfile
from app.services.interest_profile_service import apply_job_signal, apply_time_decay

logger = logging.getLogger(__name__)


@celery_app.task(name="app.tasks.profile_tasks.update_user_profile")
def update_user_profile(user_id: str):
    """Process the most recent interaction and update the user's interest profile.

    Called immediately when a user saves/unsaves/thumbs/applies (not for views).
    """
    with SyncSessionLocal() as session:
        try:
            # Get or create profile
            profile = session.execute(
                select(UserInterestProfile).where(UserInterestProfile.user_id == user_id)
            ).scalar_one_or_none()

            if not profile:
                profile = UserInterestProfile(user_id=user_id)
                session.add(profile)
                session.flush()

            # Get the most recent non-view interaction
            interaction = session.execute(
                select(UserInteraction)
                .where(
                    UserInteraction.user_id == user_id,
                    UserInteraction.interaction_type.in_(["save", "unsave", "thumbs_up", "thumbs_down", "apply_click"]),
                )
                .order_by(UserInteraction.created_at.desc())
                .limit(1)
            ).scalar_one_or_none()

            if not interaction:
                session.commit()
                return

            # Get the job and its organization
            job = session.execute(
                select(JobPosting).where(JobPosting.id == interaction.job_posting_id)
            ).scalar_one_or_none()

            if not job:
                session.commit()
                return

            org = None
            if job.organization_id:
                org = session.execute(
                    select(Organization).where(Organization.id == job.organization_id)
                ).scalar_one_or_none()

            # Apply signal
            apply_job_signal(profile, job, org, interaction.interaction_type)

            # Update total active interactions count
            active_count = session.execute(
                select(func.count(UserInteraction.id))
                .where(
                    UserInteraction.user_id == user_id,
                    UserInteraction.interaction_type.in_(["save", "thumbs_up", "thumbs_down", "apply_click"]),
                )
            ).scalar() or 0
            profile.total_interactions = active_count

            session.commit()
            logger.info("Updated interest profile for user %s (interaction: %s)", user_id, interaction.interaction_type)

        except Exception:
            session.rollback()
            logger.exception("Failed to update interest profile for user %s", user_id)
            raise


@celery_app.task(name="app.tasks.profile_tasks.batch_process_views")
def batch_process_views():
    """Process view interactions in batch (runs every 10 min via beat).

    Views are recorded server-side and processed in bulk to avoid
    dispatching individual Celery tasks for each page view.
    """
    with SyncSessionLocal() as session:
        try:
            # Find users with unprocessed views (views newer than their profile's last_updated_at)
            cutoff = datetime.now(timezone.utc) - timedelta(minutes=11)  # Slight overlap

            # Get distinct users with recent views
            users_with_views = session.execute(
                select(UserInteraction.user_id)
                .where(
                    UserInteraction.interaction_type == "view",
                    UserInteraction.created_at >= cutoff,
                )
                .distinct()
            ).scalars().all()

            processed = 0
            for uid in users_with_views:
                # Get or create profile
                profile = session.execute(
                    select(UserInterestProfile).where(UserInterestProfile.user_id == uid)
                ).scalar_one_or_none()

                if not profile:
                    profile = UserInterestProfile(user_id=uid)
                    session.add(profile)
                    session.flush()

                # Get recent views for this user
                views = session.execute(
                    select(UserInteraction)
                    .where(
                        UserInteraction.user_id == uid,
                        UserInteraction.interaction_type == "view",
                        UserInteraction.created_at >= cutoff,
                    )
                    .order_by(UserInteraction.created_at.asc())
                ).scalars().all()

                for view in views:
                    job = session.execute(
                        select(JobPosting).where(JobPosting.id == view.job_posting_id)
                    ).scalar_one_or_none()

                    if not job:
                        continue

                    org = None
                    if job.organization_id:
                        org = session.execute(
                            select(Organization).where(Organization.id == job.organization_id)
                        ).scalar_one_or_none()

                    apply_job_signal(profile, job, org, "view")
                    processed += 1

            session.commit()
            if processed:
                logger.info("Batch processed %d view interactions for %d users", processed, len(users_with_views))

        except Exception:
            session.rollback()
            logger.exception("Failed to batch process views")
            raise


@celery_app.task(name="app.tasks.profile_tasks.apply_profile_decay")
def apply_profile_decay():
    """Apply daily time decay to all interest profiles (runs at 3 AM via beat).

    14-day half-life: scores drift toward 0.5 (neutral) over time.
    """
    with SyncSessionLocal() as session:
        try:
            profiles = session.execute(select(UserInterestProfile)).scalars().all()

            updated = 0
            for profile in profiles:
                apply_time_decay(profile, days=1.0, half_life=14.0)
                updated += 1

            session.commit()
            if updated:
                logger.info("Applied time decay to %d interest profiles", updated)

        except Exception:
            session.rollback()
            logger.exception("Failed to apply profile decay")
            raise
