"""Scrape run model — audit log per scrape execution."""

from sqlalchemy import Column, String, Integer, DateTime, Text, ForeignKey
from sqlalchemy.dialects.postgresql import UUID

from app.models.base import Base, UUIDMixin


class ScrapeRun(UUIDMixin, Base):
    __tablename__ = "scrape_runs"

    source_id = Column(UUID(as_uuid=True), ForeignKey("scrape_sources.id"), nullable=False, index=True)

    started_at = Column(DateTime(timezone=True), nullable=False)
    finished_at = Column(DateTime(timezone=True))
    status = Column(String(20), nullable=False, default="running")  # running, success, failed, timeout
    jobs_found = Column(Integer, default=0)
    jobs_new = Column(Integer, default=0)
    jobs_updated = Column(Integer, default=0)
    jobs_removed = Column(Integer, default=0)
    error_message = Column(Text)

    # Relationships
    from sqlalchemy.orm import relationship
    source = relationship("ScrapeSource", back_populates="scrape_runs")
