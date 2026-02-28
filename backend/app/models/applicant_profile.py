"""Applicant profile model — stores structured resume data and credentials."""

from sqlalchemy import Column, String, Text, ForeignKey, text
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship

from app.models.base import Base, TimestampMixin, UUIDMixin


class ApplicantProfile(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "applicant_profiles"

    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False)

    # Personal info
    full_name = Column(String(200))
    email = Column(String(255))
    phone = Column(String(30))
    address_line1 = Column(String(255))
    address_line2 = Column(String(255))
    city = Column(String(100))
    state = Column(String(2))
    zip_code = Column(String(10))
    linkedin_url = Column(String(500))

    # Structured data (JSONB — serialized into AI prompts, never queried by field)
    education = Column(JSONB, server_default=text("'[]'::jsonb"), nullable=False)
    work_history = Column(JSONB, server_default=text("'[]'::jsonb"), nullable=False)
    certifications = Column(JSONB, server_default=text("'[]'::jsonb"), nullable=False)
    references = Column(JSONB, server_default=text("'[]'::jsonb"), nullable=False)
    skills = Column(JSONB, server_default=text("'{}'::jsonb"), nullable=False)
    languages = Column(JSONB, server_default=text("'[]'::jsonb"), nullable=False)

    # Full master resume for AI prompt context
    master_resume_md = Column(Text)

    # Google Docs integration
    master_resume_doc_id = Column(String(200))
    google_token_json = Column(Text)  # Encrypted via crypto.py

    # Per-platform credentials (encrypted)
    platform_credentials = Column(JSONB, server_default=text("'{}'::jsonb"), nullable=False)

    # Relationships
    user = relationship("User", back_populates="applicant_profile")
