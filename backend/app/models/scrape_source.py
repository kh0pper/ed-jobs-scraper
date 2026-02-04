"""Scrape source model — per-org platform config and scrape state."""

from sqlalchemy import Column, String, Integer, Boolean, DateTime, ForeignKey, Index
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship

from app.models.base import Base, TimestampMixin, UUIDMixin


class ScrapeSource(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "scrape_sources"

    organization_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False, index=True)

    # Platform info
    platform = Column(String(50), nullable=False, index=True)
    base_url = Column(String(500), nullable=False)
    slug = Column(String(255))

    # Scrape config
    is_active = Column(Boolean, default=True, nullable=False)
    scrape_frequency_minutes = Column(Integer, default=360, nullable=False)
    config_json = Column(JSONB, default=dict)

    # Scrape state
    last_scraped_at = Column(DateTime(timezone=True))
    last_success_at = Column(DateTime(timezone=True))
    last_job_count = Column(Integer, default=0)
    consecutive_failures = Column(Integer, default=0)

    # Discovery metadata
    discovered_by = Column(String(50), default="manual")  # manual, probe_applitrack, esc_scrape, etc.

    # Relationships
    organization = relationship("Organization", back_populates="scrape_sources")
    job_postings = relationship("JobPosting", back_populates="source")
    scrape_runs = relationship("ScrapeRun", back_populates="source")

    __table_args__ = (
        Index("idx_source_active_platform", "is_active", "platform"),
        Index("idx_source_due", "is_active", "last_scraped_at", "scrape_frequency_minutes"),
    )
