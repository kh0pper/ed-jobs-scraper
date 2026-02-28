"""Add applications table for Easy Apply pipeline.

Tracks application state through: pending → extracting → generating →
reviewing → filling → submitted (or → failed at any step).

Revision ID: 009
Revises: 008
Create Date: 2026-02-27
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision: str = "009"
down_revision: Union[str, None] = "008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "applications",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("job_posting_id", UUID(as_uuid=True), sa.ForeignKey("job_postings.id", ondelete="CASCADE"), nullable=False),

        # Pipeline status
        sa.Column("status", sa.String(30), server_default="pending", nullable=False),

        # Extracted job details
        sa.Column("job_description", sa.Text),
        sa.Column("job_requirements", sa.Text),

        # Generated documents
        sa.Column("resume_md", sa.Text),
        sa.Column("cover_letter_md", sa.Text),
        sa.Column("resume_doc_id", sa.String(200)),
        sa.Column("cover_letter_doc_id", sa.String(200)),
        sa.Column("resume_pdf_path", sa.String(500)),
        sa.Column("cover_letter_pdf_path", sa.String(500)),

        # AI metadata
        sa.Column("ai_model", sa.String(50)),
        sa.Column("ai_prompt_tokens", sa.Integer),
        sa.Column("ai_completion_tokens", sa.Integer),

        # Form filling
        sa.Column("form_data", JSONB, server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("form_screenshots", JSONB, server_default=sa.text("'[]'::jsonb"), nullable=False),

        # Tracking
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("submitted_at", sa.DateTime(timezone=True)),
        sa.Column("error_message", sa.Text),
        sa.Column("error_step", sa.String(50)),

        # User review
        sa.Column("user_approved", sa.Boolean),
        sa.Column("user_edits_made", sa.Boolean, server_default=sa.text("false"), nullable=False),

        # Timestamps
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    # Partial unique: one active application per user per job
    op.create_index(
        "idx_applications_user_job_active",
        "applications",
        ["user_id", "job_posting_id"],
        unique=True,
        postgresql_where=sa.text("status != 'failed'"),
    )
    op.create_index("idx_applications_user", "applications", ["user_id"])
    op.create_index("idx_applications_status", "applications", ["status"])


def downgrade() -> None:
    op.drop_table("applications")
