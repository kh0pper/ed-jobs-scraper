"""User interest profile model — JSONB dimension scores for ML recommendations."""

from sqlalchemy import Column, Integer, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship

from app.models.base import Base, TimestampMixin, UUIDMixin


class UserInterestProfile(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "user_interest_profiles"

    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False)

    # Dimension scores — each is a JSONB dict mapping dimension value → float [0.0, 1.0]
    category_scores = Column(JSONB, server_default="{}", nullable=False, default=dict)
    city_scores = Column(JSONB, server_default="{}", nullable=False, default=dict)
    region_scores = Column(JSONB, server_default="{}", nullable=False, default=dict)
    org_type_scores = Column(JSONB, server_default="{}", nullable=False, default=dict)

    total_interactions = Column(Integer, server_default="0", nullable=False, default=0)
    last_updated_at = Column(DateTime(timezone=True))

    # Relationships
    user = relationship("User", back_populates="interest_profile")
