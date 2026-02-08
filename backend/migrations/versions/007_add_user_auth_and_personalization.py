"""Add user auth and personalization tables.

Creates:
- users: user accounts with email/password auth
- saved_jobs: bookmarked jobs with optional notes
- user_interactions: all user-job interaction events
- user_interest_profiles: ML scoring profiles (JSONB dimension scores)

Revision ID: 007
Revises: 006
Create Date: 2026-02-07
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision: str = "007"
down_revision: Union[str, None] = "006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. users
    op.create_table(
        "users",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("email", sa.String(255), unique=True, nullable=False),
        sa.Column("display_name", sa.String(100), nullable=False),
        sa.Column("hashed_password", sa.String(255), nullable=False),
        sa.Column("is_active", sa.Boolean, server_default=sa.text("true"), nullable=False),
        sa.Column("last_login_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("idx_users_email", "users", ["email"], unique=True)

    # 2. saved_jobs
    op.create_table(
        "saved_jobs",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("job_posting_id", UUID(as_uuid=True), sa.ForeignKey("job_postings.id", ondelete="CASCADE"), nullable=False),
        sa.Column("notes", sa.Text),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("user_id", "job_posting_id", name="uq_saved_jobs_user_job"),
    )
    op.create_index("idx_saved_jobs_user", "saved_jobs", ["user_id"])
    op.create_index("idx_saved_jobs_job", "saved_jobs", ["job_posting_id"])

    # 3. user_interactions
    op.create_table(
        "user_interactions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("job_posting_id", UUID(as_uuid=True), sa.ForeignKey("job_postings.id", ondelete="CASCADE"), nullable=False),
        sa.Column("interaction_type", sa.String(20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("idx_interactions_user_type", "user_interactions", ["user_id", "interaction_type"])
    op.create_index("idx_interactions_job", "user_interactions", ["job_posting_id"])

    # 4. user_interest_profiles
    op.create_table(
        "user_interest_profiles",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False),
        sa.Column("category_scores", JSONB, server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("city_scores", JSONB, server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("region_scores", JSONB, server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("org_type_scores", JSONB, server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("total_interactions", sa.Integer, server_default=sa.text("0"), nullable=False),
        sa.Column("last_updated_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("idx_interest_profiles_user", "user_interest_profiles", ["user_id"], unique=True)


def downgrade() -> None:
    op.drop_table("user_interest_profiles")
    op.drop_table("user_interactions")
    op.drop_table("saved_jobs")
    op.drop_table("users")
