"""Initial schema — organizations, scrape_sources, job_postings, scrape_runs.

Revision ID: 001
Revises:
Create Date: 2026-02-04
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Organizations
    op.create_table(
        "organizations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tea_id", sa.String(6), unique=True, index=True, nullable=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("slug", sa.String(255), unique=True, nullable=False, index=True),
        sa.Column("org_type", sa.String(50), nullable=False, index=True),
        sa.Column("esc_region", sa.Integer, index=True),
        sa.Column("county", sa.String(100), index=True),
        sa.Column("city", sa.String(100)),
        sa.Column("state", sa.String(2), server_default="TX"),
        sa.Column("website_url", sa.String(500)),
        sa.Column("total_students", sa.Integer),
        sa.Column("district_type", sa.String(50)),
        sa.Column("charter_status", sa.String(50)),
        sa.Column("latitude", sa.Float),
        sa.Column("longitude", sa.Float),
        sa.Column("platform_status", sa.String(20), nullable=False, server_default="unmapped", index=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("idx_org_region_type", "organizations", ["esc_region", "org_type"])

    # Scrape sources
    op.create_table(
        "scrape_sources",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id"), nullable=False, index=True),
        sa.Column("platform", sa.String(50), nullable=False, index=True),
        sa.Column("base_url", sa.String(500), nullable=False),
        sa.Column("slug", sa.String(255)),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("scrape_frequency_minutes", sa.Integer, nullable=False, server_default=sa.text("360")),
        sa.Column("config_json", postgresql.JSONB, server_default=sa.text("'{}'::jsonb")),
        sa.Column("last_scraped_at", sa.DateTime(timezone=True)),
        sa.Column("last_success_at", sa.DateTime(timezone=True)),
        sa.Column("last_job_count", sa.Integer, server_default=sa.text("0")),
        sa.Column("consecutive_failures", sa.Integer, server_default=sa.text("0")),
        sa.Column("discovered_by", sa.String(50), server_default="manual"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("idx_source_active_platform", "scrape_sources", ["is_active", "platform"])
    op.create_index("idx_source_due", "scrape_sources", ["is_active", "last_scraped_at", "scrape_frequency_minutes"])

    # Job postings
    op.create_table(
        "job_postings",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id"), nullable=False, index=True),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("scrape_sources.id"), nullable=False, index=True),
        sa.Column("url_hash", sa.String(64), unique=True, nullable=False, index=True),
        sa.Column("content_hash", sa.String(64), index=True),
        sa.Column("title", sa.Text, nullable=False),
        sa.Column("application_url", sa.Text, nullable=False),
        sa.Column("location", sa.String(255)),
        sa.Column("city", sa.String(100), index=True),
        sa.Column("category", sa.String(100), index=True),
        sa.Column("raw_category", sa.String(255)),
        sa.Column("department", sa.String(255)),
        sa.Column("employment_type", sa.String(50)),
        sa.Column("salary_min", sa.Float),
        sa.Column("salary_max", sa.Float),
        sa.Column("salary_text", sa.String(255)),
        sa.Column("posting_date", sa.DateTime(timezone=True), index=True),
        sa.Column("closing_date", sa.DateTime(timezone=True)),
        sa.Column("description", sa.Text),
        sa.Column("requirements", sa.Text),
        sa.Column("latitude", sa.Float),
        sa.Column("longitude", sa.Float),
        sa.Column("geocode_status", sa.String(20), server_default="pending"),
        sa.Column("platform", sa.String(50), nullable=False, index=True),
        sa.Column("external_id", sa.String(255)),
        sa.Column("extra_data", postgresql.JSONB, server_default=sa.text("'{}'::jsonb")),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.text("true"), index=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("idx_job_category_city", "job_postings", ["category", "city"])
    op.create_index("idx_job_active_date", "job_postings", ["is_active", "posting_date"])
    op.create_index("idx_job_geo", "job_postings", ["latitude", "longitude"])
    op.create_index("idx_job_platform_external", "job_postings", ["platform", "external_id"])

    # Scrape runs
    op.create_table(
        "scrape_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("scrape_sources.id"), nullable=False, index=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("status", sa.String(20), nullable=False, server_default="running"),
        sa.Column("jobs_found", sa.Integer, server_default=sa.text("0")),
        sa.Column("jobs_new", sa.Integer, server_default=sa.text("0")),
        sa.Column("jobs_updated", sa.Integer, server_default=sa.text("0")),
        sa.Column("error_message", sa.Text),
    )


def downgrade() -> None:
    op.drop_table("scrape_runs")
    op.drop_table("job_postings")
    op.drop_table("scrape_sources")
    op.drop_table("organizations")
