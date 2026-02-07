"""Add district_demographics table.

Revision ID: 005
Revises: 004
Create Date: 2026-02-07
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "005"
down_revision: Union[str, None] = "004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "district_demographics",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True),
                   sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("school_year", sa.String(9), nullable=False),
        sa.Column("total_students", sa.Integer),
        # Percentages
        sa.Column("economically_disadvantaged", sa.Float),
        sa.Column("at_risk", sa.Float),
        sa.Column("ell", sa.Float),
        sa.Column("special_ed", sa.Float),
        sa.Column("gifted_talented", sa.Float),
        sa.Column("homeless", sa.Float),
        sa.Column("foster_care", sa.Float),
        # Counts
        sa.Column("economically_disadvantaged_count", sa.Integer),
        sa.Column("at_risk_count", sa.Integer),
        sa.Column("ell_count", sa.Integer),
        sa.Column("special_ed_count", sa.Integer),
        sa.Column("gifted_talented_count", sa.Integer),
        sa.Column("homeless_count", sa.Integer),
        sa.Column("foster_care_count", sa.Integer),
        sa.Column("bilingual_count", sa.Integer),
        sa.Column("esl_count", sa.Integer),
        sa.Column("dyslexic_count", sa.Integer),
        sa.Column("military_connected_count", sa.Integer),
        sa.Column("section_504_count", sa.Integer),
        sa.Column("title_i_count", sa.Integer),
        sa.Column("migrant_count", sa.Integer),
        # Timestamps
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_index("ix_demographics_org_id", "district_demographics", ["organization_id"])
    op.create_unique_constraint(
        "uq_demographics_org_year", "district_demographics",
        ["organization_id", "school_year"]
    )


def downgrade() -> None:
    op.drop_table("district_demographics")
