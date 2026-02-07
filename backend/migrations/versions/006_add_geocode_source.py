"""Add geocode_source column to job_postings.

Tracks where each job's coordinates came from:
- 'address' — geocoded from location field
- 'campus' — geocoded from campus field (school building)
- 'org' — inherited from organization coordinates
- 'city' — geocoded from city name
- 'legacy' — pre-existing records before provenance tracking
- 'manual' — manually set

Revision ID: 006
Revises: 005
Create Date: 2026-02-07
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "006"
down_revision: Union[str, None] = "005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("job_postings", sa.Column("geocode_source", sa.String(20)))
    op.create_index("idx_job_geocode_source", "job_postings", ["geocode_source"])

    # Backfill: mark all existing geocoded jobs as 'legacy'
    op.execute(
        "UPDATE job_postings SET geocode_source = 'legacy' "
        "WHERE geocode_status = 'success' AND latitude IS NOT NULL"
    )


def downgrade() -> None:
    op.drop_index("idx_job_geocode_source", table_name="job_postings")
    op.drop_column("job_postings", "geocode_source")
