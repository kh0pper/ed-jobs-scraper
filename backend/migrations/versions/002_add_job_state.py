"""Add state column to job_postings table.

Revision ID: 002
Revises: 001
Create Date: 2026-02-05
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add state column
    op.add_column(
        "job_postings",
        sa.Column("state", sa.String(2), nullable=True),
    )
    # Add index on state
    op.create_index("idx_job_state", "job_postings", ["state"])
    # Add composite index for state + is_active
    op.create_index("idx_job_state_active", "job_postings", ["state", "is_active"])


def downgrade() -> None:
    op.drop_index("idx_job_state_active", table_name="job_postings")
    op.drop_index("idx_job_state", table_name="job_postings")
    op.drop_column("job_postings", "state")
