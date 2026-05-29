"""Add attachments JSONB column to job_postings.

Stores references to salary schedules, PDFs, and other attachment URLs
discovered during detail-page enrichment. Each element:
{url, type, filename, fetched_at}

Revision ID: 012
Revises: 011
Create Date: 2026-05-27
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision: str = "012"
down_revision: Union[str, None] = "011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "job_postings",
        sa.Column("attachments", JSONB, server_default=sa.text("'[]'"), nullable=False),
    )


def downgrade() -> None:
    op.drop_column("job_postings", "attachments")
