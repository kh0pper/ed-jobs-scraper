"""Add enrichment_attempted_at + enrichment_status to job_postings.

Tracks per-row state for the background enrich_pending_jobs task that
fetches detail pages and backfills salary/description.

Revision ID: 011
Revises: 010
Create Date: 2026-05-14
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "011"
down_revision: Union[str, None] = "010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "job_postings",
        sa.Column("enrichment_attempted_at", sa.DateTime(timezone=True)),
    )
    op.add_column(
        "job_postings",
        sa.Column("enrichment_status", sa.String(32)),
    )
    op.create_index(
        "idx_job_enrichment_pending",
        "job_postings",
        ["platform", "enrichment_attempted_at"],
        postgresql_where=sa.text("description IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("idx_job_enrichment_pending", table_name="job_postings")
    op.drop_column("job_postings", "enrichment_status")
    op.drop_column("job_postings", "enrichment_attempted_at")
