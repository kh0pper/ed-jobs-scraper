"""User interaction model — tracks all user-job events."""

from sqlalchemy import Column, String, DateTime, ForeignKey, Index, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.models.base import Base, UUIDMixin


class UserInteraction(UUIDMixin, Base):
    __tablename__ = "user_interactions"

    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    job_posting_id = Column(UUID(as_uuid=True), ForeignKey("job_postings.id", ondelete="CASCADE"), nullable=False)
    interaction_type = Column(String(20), nullable=False)  # view, save, unsave, thumbs_up, thumbs_down, apply_click
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    # Relationships
    user = relationship("User", back_populates="interactions")
    job_posting = relationship("JobPosting")

    __table_args__ = (
        Index("idx_interactions_user_type", "user_id", "interaction_type"),
        Index("idx_interactions_job", "job_posting_id"),
    )
