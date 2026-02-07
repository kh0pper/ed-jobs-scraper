"""District demographics model — TEA ARC factor data."""

from sqlalchemy import Column, String, Integer, Float, ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.models.base import Base, TimestampMixin, UUIDMixin


class DistrictDemographics(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "district_demographics"

    organization_id = Column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    school_year = Column(String(9), nullable=False)  # "2024-2025"
    total_students = Column(Integer)

    # Percentages (nullable — FERPA masking)
    economically_disadvantaged = Column(Float)
    at_risk = Column(Float)
    ell = Column(Float)
    special_ed = Column(Float)
    gifted_talented = Column(Float)
    homeless = Column(Float)
    foster_care = Column(Float)

    # Raw counts (all nullable — FERPA masking when <10)
    economically_disadvantaged_count = Column(Integer)
    at_risk_count = Column(Integer)
    ell_count = Column(Integer)
    special_ed_count = Column(Integer)
    gifted_talented_count = Column(Integer)
    homeless_count = Column(Integer)
    foster_care_count = Column(Integer)
    bilingual_count = Column(Integer)
    esl_count = Column(Integer)
    dyslexic_count = Column(Integer)
    military_connected_count = Column(Integer)
    section_504_count = Column(Integer)
    title_i_count = Column(Integer)
    migrant_count = Column(Integer)

    # Relationships
    organization = relationship("Organization", backref="demographics")

    __table_args__ = (
        UniqueConstraint("organization_id", "school_year", name="uq_demographics_org_year"),
    )
