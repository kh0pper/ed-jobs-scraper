"""Saved job model — user bookmarks with optional notes."""

from sqlalchemy import Column, String, Text, ForeignKey, UniqueConstraint, Index
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.models.base import Base, TimestampMixin, UUIDMixin


class SavedJob(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "saved_jobs"

    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    job_posting_id = Column(UUID(as_uuid=True), ForeignKey("job_postings.id", ondelete="CASCADE"), nullable=False, index=True)
    notes = Column(Text)

    # Relationships
    user = relationship("User", back_populates="saved_jobs")
    job_posting = relationship("JobPosting")

    __table_args__ = (
        UniqueConstraint("user_id", "job_posting_id", name="uq_saved_jobs_user_job"),
    )
