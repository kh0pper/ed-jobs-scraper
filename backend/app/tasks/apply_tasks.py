"""Celery tasks for the Easy Apply pipeline.

Task chain: extract_job_details → generate_documents → [user review] → fill_application → submit_application
"""

import logging
import os
from datetime import datetime, timezone

from app.tasks.celery_app import celery_app
from app.models.base import SyncSessionLocal

# Import all related models for relationship resolution
from app.models.user import User  # noqa: F401
from app.models.organization import Organization  # noqa: F401
from app.models.job_posting import JobPosting  # noqa: F401
from app.models.scrape_source import ScrapeSource  # noqa: F401
from app.models.scrape_run import ScrapeRun  # noqa: F401
from app.models.applicant_profile import ApplicantProfile  # noqa: F401
from app.models.application import Application

logger = logging.getLogger(__name__)


@celery_app.task(
    name="app.tasks.apply_tasks.extract_job_details",
    time_limit=300,
    soft_time_limit=270,
)
def extract_job_details(application_id: str):
    """Task 1: Extract full job details from the platform.

    pending → extracting → (chains to generate_documents)
    """
    session = SyncSessionLocal()
    try:
        app = session.get(Application, application_id)
        if not app:
            logger.error("Application %s not found", application_id)
            return

        app.status = "extracting"
        session.commit()

        job = session.get(JobPosting, str(app.job_posting_id))
        if not job:
            app.status = "failed"
            app.error_step = "extraction"
            app.error_message = "Job posting not found"
            session.commit()
            return

        try:
            from app.services.job_extractor import extract_job_details as extract

            result = extract(job)

            # Cache extracted description back to job_postings
            if result["description"] and not job.description:
                job.description = result["description"]
            if result["requirements"] and not job.requirements:
                job.requirements = result["requirements"]

            # Store in application record
            app.job_description = result["description"]
            app.job_requirements = result["requirements"]

            session.commit()
            logger.info("Extracted details for application %s", application_id)

            # Chain to document generation
            generate_documents.delay(application_id)

        except Exception as e:
            logger.error("Extraction failed for %s: %s", application_id, e)
            app.status = "failed"
            app.error_step = "extraction"
            app.error_message = str(e)[:500]
            session.commit()

    finally:
        session.close()


@celery_app.task(
    name="app.tasks.apply_tasks.generate_documents",
    time_limit=900,
    soft_time_limit=840,
)
def generate_documents(application_id: str):
    """Task 2: Generate tailored resume + cover letter via Z.ai.

    extracting → generating → reviewing
    """
    session = SyncSessionLocal()
    try:
        app = session.get(Application, application_id)
        if not app:
            logger.error("Application %s not found", application_id)
            return

        app.status = "generating"
        session.commit()

        # Load related data
        profile = session.query(ApplicantProfile).filter(
            ApplicantProfile.user_id == app.user_id
        ).first()
        if not profile:
            app.status = "failed"
            app.error_step = "generation"
            app.error_message = "Applicant profile not found"
            session.commit()
            return

        job = session.get(JobPosting, str(app.job_posting_id))
        org = session.get(Organization, str(job.organization_id)) if job else None

        try:
            from app.services.resume_generator import (
                generate_tailored_resume,
                generate_cover_letter,
                validate_resume_markdown,
            )

            # Generate resume
            resume_md, resume_usage = generate_tailored_resume(profile, job, org)

            if not validate_resume_markdown(resume_md):
                # Retry once with stricter prompt
                logger.warning("Resume validation failed, retrying with stricter prompt")
                resume_md, resume_usage = generate_tailored_resume(profile, job, org)
                if not validate_resume_markdown(resume_md):
                    app.status = "failed"
                    app.error_step = "ai_validation"
                    app.error_message = "AI generated invalid resume format after retry"
                    session.commit()
                    return

            # Generate cover letter
            cover_letter_md, cl_usage = generate_cover_letter(profile, job, org)

            app.resume_md = resume_md
            app.cover_letter_md = cover_letter_md
            app.ai_model = resume_usage.get("model", "glm-4.7")
            app.ai_prompt_tokens = (
                resume_usage.get("prompt_tokens", 0) + cl_usage.get("prompt_tokens", 0)
            )
            app.ai_completion_tokens = (
                resume_usage.get("completion_tokens", 0) + cl_usage.get("completion_tokens", 0)
            )

            # Try Google Docs, fall back to WeasyPrint
            pdf_dir = os.environ.get("APPLY_PDF_DIR", "/app/data/pdfs")
            os.makedirs(pdf_dir, exist_ok=True)

            try:
                _create_google_docs(app, profile, resume_md, cover_letter_md, pdf_dir)
            except Exception as google_err:
                logger.warning("Google Docs failed, using WeasyPrint fallback: %s", google_err)
                _create_weasyprint_pdfs(app, resume_md, cover_letter_md, pdf_dir)

            app.status = "reviewing"
            session.commit()
            logger.info("Documents generated for application %s", application_id)

        except Exception as e:
            logger.error("Document generation failed for %s: %s", application_id, e)
            app.status = "failed"
            app.error_step = "generation"
            app.error_message = str(e)[:500]
            session.commit()

    finally:
        session.close()


def _create_google_docs(app, profile, resume_md, cover_letter_md, pdf_dir):
    """Create Google Docs and export PDFs."""
    if not profile.google_token_json:
        raise ValueError("No Google token available")

    from app.services.google_client import get_google_services, create_doc, format_and_export

    docs_svc, drive_svc = get_google_services(profile.google_token_json)

    # Create and format resume
    resume_doc_id = create_doc(drive_svc, f"Resume - {app.id}")
    resume_pdf = format_and_export(docs_svc, drive_svc, resume_doc_id, resume_md, "resume")
    app.resume_doc_id = resume_doc_id

    # Create and format cover letter
    cl_doc_id = create_doc(drive_svc, f"Cover Letter - {app.id}")
    cl_pdf = format_and_export(docs_svc, drive_svc, cl_doc_id, cover_letter_md, "cover_letter")
    app.cover_letter_doc_id = cl_doc_id

    # Save PDFs
    resume_path = os.path.join(pdf_dir, f"resume_{app.id}.pdf")
    cl_path = os.path.join(pdf_dir, f"cover_letter_{app.id}.pdf")

    with open(resume_path, "wb") as f:
        f.write(resume_pdf)
    with open(cl_path, "wb") as f:
        f.write(cl_pdf)

    app.resume_pdf_path = resume_path
    app.cover_letter_pdf_path = cl_path


def _create_weasyprint_pdfs(app, resume_md, cover_letter_md, pdf_dir):
    """Fallback: generate PDFs locally with WeasyPrint."""
    from app.services.google_client import markdown_to_pdf_weasyprint

    resume_pdf = markdown_to_pdf_weasyprint(resume_md, "resume")
    cl_pdf = markdown_to_pdf_weasyprint(cover_letter_md, "cover_letter")

    resume_path = os.path.join(pdf_dir, f"resume_{app.id}.pdf")
    cl_path = os.path.join(pdf_dir, f"cover_letter_{app.id}.pdf")

    with open(resume_path, "wb") as f:
        f.write(resume_pdf)
    with open(cl_path, "wb") as f:
        f.write(cl_pdf)

    app.resume_pdf_path = resume_path
    app.cover_letter_pdf_path = cl_path


@celery_app.task(
    name="app.tasks.apply_tasks.fill_application",
    time_limit=1200,
    soft_time_limit=1100,
    queue="apply",
)
def fill_application(application_id: str):
    """Task 3: Fill application form via browser automation.

    reviewing → filling (only after user_approved = True)
    """
    import asyncio

    session = SyncSessionLocal()
    try:
        app = session.get(Application, application_id)
        if not app:
            logger.error("Application %s not found", application_id)
            return

        if not app.user_approved:
            logger.warning("Application %s not yet approved", application_id)
            return

        app.status = "filling"
        session.commit()

        job = session.get(JobPosting, str(app.job_posting_id))
        if not job:
            app.status = "failed"
            app.error_step = "form_fill"
            app.error_message = "Job posting not found"
            session.commit()
            return

        # Verify job still exists on platform
        try:
            import httpx
            resp = httpx.head(job.application_url, timeout=15, follow_redirects=True)
            if resp.status_code >= 400:
                app.status = "failed"
                app.error_step = "job_removed"
                app.error_message = f"Job page returned HTTP {resp.status_code}"
                session.commit()
                return
        except Exception as e:
            logger.warning("Could not verify job URL: %s", e)

        profile = session.query(ApplicantProfile).filter(
            ApplicantProfile.user_id == app.user_id
        ).first()

        try:
            from app.services.form_filler import get_form_filler

            filler = get_form_filler(job.platform)
            if filler is None:
                # No form filler for this platform — leave at "filling" with message
                app.error_step = "form_fill"
                app.error_message = (
                    f"Automated form filling not yet available for {job.platform}. "
                    f"Your tailored resume and cover letter are ready — "
                    f"use 'Apply Now' to open the application page manually."
                )
                app.status = "failed"
                session.commit()
                return

            # Run async form filler from sync context
            result = asyncio.run(
                filler.run(job, profile, app)
            )

            app.form_data = result.get("form_data", {})
            app.form_screenshots = result.get("screenshots", [])
            session.commit()

            logger.info("Form filled for application %s", application_id)

        except Exception as e:
            logger.error("Form filling failed for %s: %s", application_id, e)
            app.status = "failed"
            app.error_step = "form_fill"
            app.error_message = str(e)[:500]
            session.commit()

    finally:
        session.close()


@celery_app.task(
    name="app.tasks.apply_tasks.submit_application",
    time_limit=300,
    soft_time_limit=270,
    queue="apply",
)
def submit_application(application_id: str):
    """Task 4: Submit the filled application form.

    filling → submitted
    """
    import asyncio

    session = SyncSessionLocal()
    try:
        app = session.get(Application, application_id)
        if not app:
            logger.error("Application %s not found", application_id)
            return

        job = session.get(JobPosting, str(app.job_posting_id))
        if not job:
            app.status = "failed"
            app.error_step = "submission"
            app.error_message = "Job posting not found"
            session.commit()
            return

        try:
            from app.services.form_filler import get_form_filler

            filler = get_form_filler(job.platform)
            if filler is None:
                app.status = "failed"
                app.error_step = "submission"
                app.error_message = f"No form filler for {job.platform}"
                session.commit()
                return

            result = asyncio.run(filler.submit(job, app))

            app.status = "submitted"
            app.submitted_at = datetime.now(timezone.utc)
            if result.get("screenshot"):
                screenshots = list(app.form_screenshots or [])
                screenshots.append(result["screenshot"])
                app.form_screenshots = screenshots
            session.commit()

            logger.info("Application %s submitted successfully", application_id)

        except Exception as e:
            logger.error("Submission failed for %s: %s", application_id, e)
            app.status = "failed"
            app.error_step = "submission"
            app.error_message = str(e)[:500]
            session.commit()

    finally:
        session.close()


@celery_app.task(name="app.tasks.apply_tasks.cleanup_old_screenshots")
def cleanup_old_screenshots():
    """Remove screenshot files older than 30 days."""
    import glob
    from datetime import timedelta

    screenshot_dir = os.environ.get("APPLY_SCREENSHOT_DIR", "/app/data/screenshots")
    if not os.path.isdir(screenshot_dir):
        return

    cutoff = datetime.now(timezone.utc).timestamp() - timedelta(days=30).total_seconds()
    removed = 0

    for path in glob.glob(os.path.join(screenshot_dir, "*.png")):
        if os.path.getmtime(path) < cutoff:
            os.remove(path)
            removed += 1

    if removed:
        logger.info("Cleaned up %d old screenshots", removed)
