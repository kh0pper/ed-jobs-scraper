"""Job posting model — core job table."""

from sqlalchemy import Column, String, Float, Boolean, DateTime, Text, ForeignKey, Index, Integer
from sqlalchemy.dialects.postgresql import UUID, JSONB

from app.models.base import Base, TimestampMixin, UUIDMixin


class JobPosting(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "job_postings"

    organization_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False, index=True)
    source_id = Column(UUID(as_uuid=True), ForeignKey("scrape_sources.id"), nullable=False, index=True)

    # Dedup
    url_hash = Column(String(64), unique=True, nullable=False, index=True)
    content_hash = Column(String(64), index=True)

    # Core
    title = Column(Text, nullable=False)
    application_url = Column(Text, nullable=False)

    # Structured fields (populated when available)
    location = Column(String(255))
    city = Column(String(100), index=True)
    state = Column(String(2), index=True)  # 2-letter state code (TX, CA, etc.)
    category = Column(String(100), index=True)  # normalized
    raw_category = Column(String(255))
    department = Column(String(255))
    employment_type = Column(String(50))  # full_time, part_time, temporary, etc.
    salary_min = Column(Float)
    salary_max = Column(Float)
    salary_text = Column(String(255))
    posting_date = Column(DateTime(timezone=True), index=True)
    closing_date = Column(DateTime(timezone=True))
    description = Column(Text)
    requirements = Column(Text)

    # Geocoding
    latitude = Column(Float)
    longitude = Column(Float)
    geocode_status = Column(String(20), default="pending")  # pending, success, failed, skipped
    geocode_source = Column(String(20))  # address, campus, org, city, legacy, manual

    # Platform metadata
    platform = Column(String(50), nullable=False, index=True)
    external_id = Column(String(255))
    extra_data = Column(JSONB, default=dict)

    # Location - specific campus/school (when available from platform)
    campus = Column(String(255))

    # Lifecycle
    first_seen_at = Column(DateTime(timezone=True), nullable=False)
    last_seen_at = Column(DateTime(timezone=True), nullable=False)
    is_active = Column(Boolean, default=True, nullable=False, index=True)
    last_seen_run_id = Column(UUID(as_uuid=True), ForeignKey("scrape_runs.id"), index=True)
    removal_detected_at = Column(DateTime(timezone=True))
    reactivation_count = Column(Integer, default=0, nullable=False)

    # Relationships (import strings to avoid circular imports)
    from sqlalchemy.orm import relationship
    organization = relationship("Organization", back_populates="job_postings")
    source = relationship("ScrapeSource", back_populates="job_postings")

    __table_args__ = (
        Index("idx_job_category_city", "category", "city"),
        Index("idx_job_active_date", "is_active", "posting_date"),
        Index("idx_job_geo", "latitude", "longitude"),
        Index("idx_job_platform_external", "platform", "external_id"),
        Index("idx_job_state_active", "state", "is_active"),
        Index("idx_job_last_run", "source_id", "last_seen_run_id"),
        Index("idx_job_removal", "is_active", "removal_detected_at"),
        Index("idx_job_geocode_source", "geocode_source"),
    )
