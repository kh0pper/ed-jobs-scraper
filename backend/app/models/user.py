"""User model for authentication."""

from sqlalchemy import Column, String, Boolean, DateTime
from sqlalchemy.orm import relationship

from app.models.base import Base, TimestampMixin, UUIDMixin


class User(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "users"

    email = Column(String(255), unique=True, nullable=False, index=True)
    display_name = Column(String(100), nullable=False)
    hashed_password = Column(String(255), nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    last_login_at = Column(DateTime(timezone=True))

    # Relationships
    saved_jobs = relationship("SavedJob", back_populates="user", cascade="all, delete-orphan")
    interactions = relationship("UserInteraction", back_populates="user", cascade="all, delete-orphan")
    interest_profile = relationship("UserInterestProfile", back_populates="user", uselist=False, cascade="all, delete-orphan")
