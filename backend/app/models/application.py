"""Application model — tracks Easy Apply pipeline state."""

from sqlalchemy import Column, String, Text, Boolean, DateTime, Integer, ForeignKey, Index, text
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship

from app.models.base import Base, TimestampMixin, UUIDMixin


class Application(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "applications"

    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    job_posting_id = Column(UUID(as_uuid=True), ForeignKey("job_postings.id", ondelete="CASCADE"), nullable=False)

    # Pipeline status: pending → extracting → generating → reviewing → filling → submitted
    # Or → failed at any step
    status = Column(String(30), default="pending", nullable=False)

    # Extracted job details
    job_description = Column(Text)
    job_requirements = Column(Text)

    # Generated documents
    resume_md = Column(Text)
    cover_letter_md = Column(Text)
    resume_doc_id = Column(String(200))
    cover_letter_doc_id = Column(String(200))
    resume_pdf_path = Column(String(500))
    cover_letter_pdf_path = Column(String(500))

    # AI metadata
    ai_model = Column(String(50))
    ai_prompt_tokens = Column(Integer)
    ai_completion_tokens = Column(Integer)

    # Form filling
    form_data = Column(JSONB, server_default=text("'{}'::jsonb"), nullable=False)
    form_screenshots = Column(JSONB, server_default=text("'[]'::jsonb"), nullable=False)

    # Tracking
    started_at = Column(DateTime(timezone=True))
    submitted_at = Column(DateTime(timezone=True))
    error_message = Column(Text)
    error_step = Column(String(50))

    # User review
    user_approved = Column(Boolean)
    user_edits_made = Column(Boolean, default=False, nullable=False)

    # Relationships
    user = relationship("User", back_populates="applications")
    job_posting = relationship("JobPosting")

    __table_args__ = (
        # Only one non-failed application per user per job
        Index(
            "idx_applications_user_job_active",
            "user_id", "job_posting_id",
            unique=True,
            postgresql_where=text("status != 'failed'"),
        ),
        Index("idx_applications_user", "user_id"),
        Index("idx_applications_status", "status"),
    )
