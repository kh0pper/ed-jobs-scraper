"""Add PostGIS extension and geography columns.

Revision ID: 003
Revises: 002
Create Date: 2026-02-05
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "003"
down_revision: Union[str, None] = "002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Enable PostGIS extension
    op.execute("CREATE EXTENSION IF NOT EXISTS postgis;")

    # Add geography column to organizations (for district locations)
    op.execute("""
        ALTER TABLE organizations
        ADD COLUMN IF NOT EXISTS geog geography(POINT, 4326);
    """)

    # Add geography column to job_postings (for job locations)
    op.execute("""
        ALTER TABLE job_postings
        ADD COLUMN IF NOT EXISTS geog geography(POINT, 4326);
    """)

    # Create spatial indexes
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_organizations_geog
        ON organizations USING GIST (geog);
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_job_postings_geog
        ON job_postings USING GIST (geog);
    """)

    # Backfill existing lat/lon to geography columns
    op.execute("""
        UPDATE organizations
        SET geog = ST_SetSRID(ST_MakePoint(longitude, latitude), 4326)::geography
        WHERE latitude IS NOT NULL AND longitude IS NOT NULL AND geog IS NULL;
    """)
    op.execute("""
        UPDATE job_postings
        SET geog = ST_SetSRID(ST_MakePoint(longitude, latitude), 4326)::geography
        WHERE latitude IS NOT NULL AND longitude IS NOT NULL AND geog IS NULL;
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_job_postings_geog;")
    op.execute("DROP INDEX IF EXISTS idx_organizations_geog;")
    op.execute("ALTER TABLE job_postings DROP COLUMN IF EXISTS geog;")
    op.execute("ALTER TABLE organizations DROP COLUMN IF EXISTS geog;")
    # Note: We don't drop the PostGIS extension as other tables might use it
