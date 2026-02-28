"""Digest preference model — controls weekly email delivery."""

from sqlalchemy import Column, String, Boolean, Integer, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship

from app.models.base import Base, TimestampMixin, UUIDMixin


class DigestPreference(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "digest_preferences"

    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False)

    is_enabled = Column(Boolean, default=True, nullable=False)
    frequency = Column(String(20), default="weekly", nullable=False)
    day_of_week = Column(Integer, default=1, nullable=False)  # Monday
    max_jobs = Column(Integer, default=20, nullable=False)

    # Filters (NULL = all)
    categories = Column(JSONB)  # e.g. ["Teacher", "Administrator"]
    regions = Column(JSONB)     # e.g. [4, 10, 13] — ESC regions

    # Watermarks
    last_sent_at = Column(DateTime(timezone=True))
    last_job_seen_at = Column(DateTime(timezone=True))

    # Relationships
    user = relationship("User", back_populates="digest_preference")
