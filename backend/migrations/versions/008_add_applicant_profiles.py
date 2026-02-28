"""Add applicant profiles table.

Stores structured resume data, Google OAuth tokens (encrypted),
and per-platform credentials for the Easy Apply pipeline.

Revision ID: 008
Revises: 007
Create Date: 2026-02-27
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision: str = "008"
down_revision: Union[str, None] = "007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "applicant_profiles",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False),

        # Personal info
        sa.Column("full_name", sa.String(200)),
        sa.Column("email", sa.String(255)),
        sa.Column("phone", sa.String(30)),
        sa.Column("address_line1", sa.String(255)),
        sa.Column("address_line2", sa.String(255)),
        sa.Column("city", sa.String(100)),
        sa.Column("state", sa.String(2)),
        sa.Column("zip_code", sa.String(10)),
        sa.Column("linkedin_url", sa.String(500)),

        # Structured JSONB data
        sa.Column("education", JSONB, server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("work_history", JSONB, server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("certifications", JSONB, server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("references", JSONB, server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("skills", JSONB, server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("languages", JSONB, server_default=sa.text("'[]'::jsonb"), nullable=False),

        # Master resume
        sa.Column("master_resume_md", sa.Text),

        # Google Docs integration
        sa.Column("master_resume_doc_id", sa.String(200)),
        sa.Column("google_token_json", sa.Text),  # Encrypted

        # Platform credentials (encrypted values in JSONB)
        sa.Column("platform_credentials", JSONB, server_default=sa.text("'{}'::jsonb"), nullable=False),

        # Timestamps
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("idx_applicant_profiles_user", "applicant_profiles", ["user_id"], unique=True)


def downgrade() -> None:
    op.drop_table("applicant_profiles")
