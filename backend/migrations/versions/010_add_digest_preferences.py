"""Add digest preferences table for weekly email digest.

Revision ID: 010
Revises: 009
Create Date: 2026-02-27
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision: str = "010"
down_revision: Union[str, None] = "009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "digest_preferences",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False),

        sa.Column("is_enabled", sa.Boolean, server_default=sa.text("true"), nullable=False),
        sa.Column("frequency", sa.String(20), server_default="weekly", nullable=False),
        sa.Column("day_of_week", sa.Integer, server_default=sa.text("1"), nullable=False),
        sa.Column("max_jobs", sa.Integer, server_default=sa.text("20"), nullable=False),

        sa.Column("categories", JSONB),
        sa.Column("regions", JSONB),

        sa.Column("last_sent_at", sa.DateTime(timezone=True)),
        sa.Column("last_job_seen_at", sa.DateTime(timezone=True)),

        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("idx_digest_preferences_user", "digest_preferences", ["user_id"], unique=True)


def downgrade() -> None:
    op.drop_table("digest_preferences")
