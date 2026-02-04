"""Organization model — districts, charters, nonprofits, etc."""

from sqlalchemy import Column, String, Integer, Float, Index
from sqlalchemy.orm import relationship

from app.models.base import Base, TimestampMixin, UUIDMixin


class Organization(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "organizations"

    # TEA linkage
    tea_id = Column(String(6), unique=True, index=True, nullable=True)

    # Identity
    name = Column(String(255), nullable=False)
    slug = Column(String(255), unique=True, nullable=False, index=True)
    org_type = Column(
        String(50), nullable=False, index=True,
    )  # isd, charter, esc, nonprofit, state_agency, association, for_profit, higher_ed

    # Geography
    esc_region = Column(Integer, index=True)
    county = Column(String(100), index=True)
    city = Column(String(100))
    state = Column(String(2), default="TX")
    website_url = Column(String(500))

    # TEA data
    total_students = Column(Integer)
    district_type = Column(String(50))
    charter_status = Column(String(50))

    # Geocoding
    latitude = Column(Float)
    longitude = Column(Float)

    # Platform discovery status
    platform_status = Column(
        String(20), default="unmapped", nullable=False, index=True,
    )  # mapped, probing, unmapped, no_online_postings

    # Relationships
    scrape_sources = relationship("ScrapeSource", back_populates="organization")
    job_postings = relationship("JobPosting", back_populates="organization")

    __table_args__ = (
        Index("idx_org_region_type", "esc_region", "org_type"),
    )
