"""Celery application configuration and beat schedule."""

from celery import Celery
from celery.schedules import crontab

from app.config import get_settings

settings = get_settings()

celery_app = Celery(
    "edjobs",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=[
        "app.tasks.scrape_tasks",
        "app.tasks.maintenance_tasks",
        "app.tasks.data_quality_tasks",
    ],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="US/Central",
    task_track_started=True,
    task_time_limit=600,
    task_soft_time_limit=540,
    worker_prefetch_multiplier=1,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
)

celery_app.conf.beat_schedule = {
    "dispatch-due-scrapes": {
        "task": "app.tasks.scrape_tasks.dispatch_due_scrapes",
        "schedule": crontab(minute="*/30"),
    },
    "geocode-pending-jobs": {
        "task": "app.tasks.data_quality_tasks.geocode_pending_jobs",
        "schedule": crontab(minute=0, hour="*/2"),
    },
    "geocode-pending-orgs": {
        "task": "app.tasks.data_quality_tasks.geocode_pending_organizations",
        "schedule": crontab(minute=30, hour="*/4"),
    },
    "normalize-job-categories": {
        "task": "app.tasks.data_quality_tasks.normalize_job_categories",
        "schedule": crontab(minute="*/15"),
    },
    "mark-stale-postings": {
        "task": "app.tasks.maintenance_tasks.mark_stale_postings",
        "schedule": crontab(minute=0, hour=4),
    },
    "cleanup-old-postings": {
        "task": "app.tasks.maintenance_tasks.cleanup_old_postings",
        "schedule": crontab(minute=0, hour=5),
    },
    "deduplicate-postings": {
        "task": "app.tasks.maintenance_tasks.deduplicate_postings",
        "schedule": crontab(minute=30, hour=3),
    },
}
