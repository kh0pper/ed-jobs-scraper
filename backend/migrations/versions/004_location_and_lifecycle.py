"""Add location fields and job lifecycle tracking.

Revision ID: 004
Revises: 003
Create Date: 2026-02-05

Adds:
- job_postings.campus: Specific school/campus location
- job_postings.last_seen_run_id: FK to most recent scrape run that saw this job
- job_postings.removal_detected_at: When job was detected as removed
- job_postings.reactivation_count: Times job reappeared after being marked removed
- scrape_runs.jobs_removed: Count of jobs detected as removed in this run
- organizations.city_source: How the city was derived (county_seat, manual, geocode)
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision: str = "004"
down_revision: Union[str, None] = "003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # JobPosting additions
    op.add_column("job_postings", sa.Column("campus", sa.String(255), nullable=True))
    op.add_column("job_postings", sa.Column(
        "last_seen_run_id",
        UUID(as_uuid=True),
        sa.ForeignKey("scrape_runs.id"),
        nullable=True,
    ))
    op.add_column("job_postings", sa.Column(
        "removal_detected_at",
        sa.DateTime(timezone=True),
        nullable=True,
    ))
    op.add_column("job_postings", sa.Column(
        "reactivation_count",
        sa.Integer,
        server_default="0",
        nullable=False,
    ))

    # JobPosting indexes
    op.create_index(
        "idx_job_last_run",
        "job_postings",
        ["source_id", "last_seen_run_id"],
    )
    op.create_index(
        "idx_job_removal",
        "job_postings",
        ["is_active", "removal_detected_at"],
    )

    # ScrapeRun additions
    op.add_column("scrape_runs", sa.Column(
        "jobs_removed",
        sa.Integer,
        server_default="0",
        nullable=False,
    ))

    # Organization additions
    op.add_column("organizations", sa.Column(
        "city_source",
        sa.String(20),
        nullable=True,
    ))


def downgrade() -> None:
    # Organization
    op.drop_column("organizations", "city_source")

    # ScrapeRun
    op.drop_column("scrape_runs", "jobs_removed")

    # JobPosting indexes
    op.drop_index("idx_job_removal", table_name="job_postings")
    op.drop_index("idx_job_last_run", table_name="job_postings")

    # JobPosting columns
    op.drop_column("job_postings", "reactivation_count")
    op.drop_column("job_postings", "removal_detected_at")
    op.drop_column("job_postings", "last_seen_run_id")
    op.drop_column("job_postings", "campus")
