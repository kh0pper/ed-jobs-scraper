"""Celery tasks for weekly email digest."""

import logging
from datetime import datetime, timezone

from app.tasks.celery_app import celery_app
from app.models.base import SyncSessionLocal

# Import all related models for relationship resolution
from app.models.user import User  # noqa: F401
from app.models.organization import Organization  # noqa: F401
from app.models.job_posting import JobPosting  # noqa: F401
from app.models.application import Application  # noqa: F401
from app.models.digest_preference import DigestPreference

from sqlalchemy import select

logger = logging.getLogger(__name__)


@celery_app.task(name="app.tasks.digest_tasks.send_weekly_digests")
def send_weekly_digests():
    """Send digest emails to all enabled users."""
    session = SyncSessionLocal()
    try:
        # Find all users with enabled digests
        result = session.execute(
            select(DigestPreference).where(DigestPreference.is_enabled == True)
        )
        preferences = result.scalars().all()

        dispatched = 0
        for pref in preferences:
            send_user_digest.delay(str(pref.user_id))
            dispatched += 1

        logger.info("Weekly digest: dispatched %d user digest tasks", dispatched)

    finally:
        session.close()


@celery_app.task(name="app.tasks.digest_tasks.send_user_digest")
def send_user_digest(user_id: str):
    """Send digest email to a single user."""
    session = SyncSessionLocal()
    try:
        user = session.get(User, user_id)
        if not user:
            logger.error("User %s not found", user_id)
            return

        pref = session.execute(
            select(DigestPreference).where(DigestPreference.user_id == user_id)
        ).scalar_one_or_none()

        if not pref or not pref.is_enabled:
            logger.info("Digest disabled for user %s", user_id)
            return

        from app.services.digest_builder import build_digest
        from app.services.mailer import send_email
        from jinja2 import Environment, FileSystemLoader

        digest = build_digest(session, user_id, pref)

        if not digest["all_jobs"]:
            logger.info("No new jobs for user %s, skipping digest", user_id)
            return

        # Render email template
        env = Environment(loader=FileSystemLoader("app/templates"))
        template = env.get_template("email/digest.html")

        # Generate signed unsubscribe token
        from itsdangerous import URLSafeSerializer
        from app.config import get_settings
        settings = get_settings()
        s = URLSafeSerializer(settings.secret_key, salt="digest-unsubscribe")
        unsubscribe_token = s.dumps(str(user_id))

        html = template.render(
            user=user,
            digest=digest,
            unsubscribe_url=f"{digest['app_url']}/digest/unsubscribe?token={unsubscribe_token}",
        )

        subject = f"Texas Ed Jobs: {digest['total_new']} new jobs this week"

        success = send_email(
            to=user.email,
            subject=subject,
            html=html,
            text=f"{digest['total_new']} new education jobs in Texas. View at {digest['app_url']}/for-you",
        )

        if success:
            pref.last_sent_at = datetime.now(timezone.utc)
            pref.last_job_seen_at = digest["date_range"][1]
            session.commit()
            logger.info("Digest sent to %s (%d jobs)", user.email, len(digest["all_jobs"]))

    finally:
        session.close()
