"""Easy Apply routes — profile management and application pipeline."""

import json
import logging
import os

from fastapi import APIRouter, Depends, Form, Request, Query
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.base import get_db
from app.models.user import User
from app.models.applicant_profile import ApplicantProfile
from app.models.application import Application
from app.models.job_posting import JobPosting
from app.models.organization import Organization
from app.dependencies.auth import require_user, ensure_csrf_token, validate_csrf_token

logger = logging.getLogger(__name__)
settings = get_settings()

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


async def _ctx(request, db, user, **extra):
    """Build template context."""
    csrf_token = ensure_csrf_token(request)
    return {
        "request": request,
        "current_user": user,
        "csrf_token": csrf_token,
        **extra,
    }


# --- Applicant Profile ---

@router.get("/apply/profile", response_class=HTMLResponse)
async def profile_page(
    request: Request,
    user: User = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    """Applicant profile editing page."""
    result = await db.execute(
        select(ApplicantProfile).where(ApplicantProfile.user_id == user.id)
    )
    profile = result.scalar_one_or_none()

    ctx = await _ctx(request, db, user, profile=profile)
    return templates.TemplateResponse("apply/profile.html", ctx)


@router.post("/apply/profile", response_class=HTMLResponse)
async def save_profile(
    request: Request,
    user: User = Depends(require_user),
    db: AsyncSession = Depends(get_db),
    csrf_token: str = Form(""),
    full_name: str = Form(""),
    email: str = Form(""),
    phone: str = Form(""),
    address_line1: str = Form(""),
    address_line2: str = Form(""),
    city: str = Form(""),
    state: str = Form(""),
    zip_code: str = Form(""),
    linkedin_url: str = Form(""),
    education_json: str = Form("[]"),
    work_history_json: str = Form("[]"),
    certifications_json: str = Form("[]"),
    references_json: str = Form("[]"),
    skills_json: str = Form("{}"),
    languages_json: str = Form("[]"),
):
    """Save applicant profile."""
    if not validate_csrf_token(request, csrf_token):
        return RedirectResponse("/apply/profile", status_code=303)

    result = await db.execute(
        select(ApplicantProfile).where(ApplicantProfile.user_id == user.id)
    )
    profile = result.scalar_one_or_none()

    if not profile:
        profile = ApplicantProfile(user_id=user.id)
        db.add(profile)

    profile.full_name = full_name
    profile.email = email
    profile.phone = phone
    profile.address_line1 = address_line1
    profile.address_line2 = address_line2
    profile.city = city
    profile.state = state
    profile.zip_code = zip_code
    profile.linkedin_url = linkedin_url

    # Parse JSONB fields
    try:
        profile.education = json.loads(education_json)
    except json.JSONDecodeError:
        pass
    try:
        profile.work_history = json.loads(work_history_json)
    except json.JSONDecodeError:
        pass
    try:
        profile.certifications = json.loads(certifications_json)
    except json.JSONDecodeError:
        pass
    try:
        profile.references = json.loads(references_json)
    except json.JSONDecodeError:
        pass
    try:
        profile.skills = json.loads(skills_json)
    except json.JSONDecodeError:
        pass
    try:
        profile.languages = json.loads(languages_json)
    except json.JSONDecodeError:
        pass

    return RedirectResponse("/apply/profile?saved=1", status_code=303)


# --- Google OAuth ---

@router.get("/apply/profile/google")
async def google_oauth_start(
    request: Request,
    user: User = Depends(require_user),
):
    """Initiate Google OAuth for Docs/Drive access."""
    from google_auth_oauthlib.flow import Flow

    creds_file = settings.google_credentials_file
    if not os.path.exists(creds_file):
        return RedirectResponse("/apply/profile?error=google_not_configured", status_code=303)

    flow = Flow.from_client_secrets_file(
        creds_file,
        scopes=[
            "https://www.googleapis.com/auth/drive.file",
            "https://www.googleapis.com/auth/documents",
        ],
        redirect_uri=str(request.url_for("google_oauth_callback")),
    )

    authorization_url, state = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
    )

    request.session["google_oauth_state"] = state
    return RedirectResponse(authorization_url)


@router.get("/apply/profile/google/callback")
async def google_oauth_callback(
    request: Request,
    user: User = Depends(require_user),
    db: AsyncSession = Depends(get_db),
    code: str = Query(""),
    state: str = Query(""),
):
    """Handle Google OAuth callback."""
    from google_auth_oauthlib.flow import Flow
    from app.services.crypto import encrypt

    stored_state = request.session.get("google_oauth_state")
    if not stored_state or stored_state != state:
        return RedirectResponse("/apply/profile?error=oauth_state_mismatch", status_code=303)

    creds_file = settings.google_credentials_file
    flow = Flow.from_client_secrets_file(
        creds_file,
        scopes=[
            "https://www.googleapis.com/auth/drive.file",
            "https://www.googleapis.com/auth/documents",
        ],
        redirect_uri=str(request.url_for("google_oauth_callback")),
        state=state,
    )

    flow.fetch_token(code=code)
    creds = flow.credentials

    # Store encrypted token
    token_data = {
        "token": creds.token,
        "refresh_token": creds.refresh_token,
        "token_uri": creds.token_uri,
        "client_id": creds.client_id,
        "client_secret": creds.client_secret,
        "scopes": list(creds.scopes),
    }

    result = await db.execute(
        select(ApplicantProfile).where(ApplicantProfile.user_id == user.id)
    )
    profile = result.scalar_one_or_none()
    if not profile:
        profile = ApplicantProfile(user_id=user.id)
        db.add(profile)

    profile.google_token_json = encrypt(json.dumps(token_data))
    return RedirectResponse("/apply/profile?google=connected", status_code=303)


# --- Easy Apply Pipeline ---

@router.post("/apply/{job_id}")
async def start_application(
    request: Request,
    job_id: str,
    user: User = Depends(require_user),
    db: AsyncSession = Depends(get_db),
    csrf_token: str = Form(""),
):
    """Start Easy Apply pipeline for a job."""
    if not validate_csrf_token(request, csrf_token):
        return RedirectResponse(f"/jobs/{job_id}", status_code=303)

    # Check user has a profile
    profile_result = await db.execute(
        select(ApplicantProfile).where(ApplicantProfile.user_id == user.id)
    )
    profile = profile_result.scalar_one_or_none()
    if not profile or not profile.full_name:
        return RedirectResponse("/apply/profile?error=profile_required", status_code=303)

    # Check for existing non-failed application
    existing = await db.execute(
        select(Application).where(
            Application.user_id == user.id,
            Application.job_posting_id == job_id,
            Application.status != "failed",
        )
    )
    if existing.scalar_one_or_none():
        return RedirectResponse(f"/apply/{job_id}/status", status_code=303)

    # Create application
    from datetime import datetime, timezone
    app = Application(
        user_id=user.id,
        job_posting_id=job_id,
        status="pending",
        started_at=datetime.now(timezone.utc),
    )
    db.add(app)
    await db.commit()

    # Dispatch extraction task (after commit so Celery can find the row)
    from app.tasks.apply_tasks import extract_job_details as extract_task
    extract_task.delay(str(app.id))

    return RedirectResponse(f"/apply/{job_id}/status", status_code=303)


@router.get("/apply/{job_id}/status", response_class=HTMLResponse)
async def application_status(
    request: Request,
    job_id: str,
    user: User = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    """Application status page with HTMX polling."""
    # Show the most recent application (including failed ones for retry)
    result = await db.execute(
        select(Application).where(
            Application.user_id == user.id,
            Application.job_posting_id == job_id,
        ).order_by(Application.created_at.desc())
    )
    application = result.scalars().first()

    job_result = await db.execute(
        select(JobPosting, Organization.name.label("org_name"))
        .outerjoin(Organization, JobPosting.organization_id == Organization.id)
        .where(JobPosting.id == job_id)
    )
    row = job_result.first()
    job = row[0] if row else None
    org_name = row[1] if row else None

    ctx = await _ctx(request, db, user,
                     application=application, job=job, org_name=org_name)
    return templates.TemplateResponse("apply/status.html", ctx)


@router.get("/apply/{job_id}/status/partial", response_class=HTMLResponse)
async def application_status_partial(
    request: Request,
    job_id: str,
    user: User = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    """HTMX partial for polling application status."""
    result = await db.execute(
        select(Application).where(
            Application.user_id == user.id,
            Application.job_posting_id == job_id,
        ).order_by(Application.created_at.desc())
    )
    application = result.scalars().first()

    ctx = await _ctx(request, db, user, application=application)
    return templates.TemplateResponse("partials/apply_status.html", ctx)


@router.get("/apply/{job_id}/review", response_class=HTMLResponse)
async def review_page(
    request: Request,
    job_id: str,
    user: User = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    """Review generated resume + cover letter before form filling."""
    result = await db.execute(
        select(Application).where(
            Application.user_id == user.id,
            Application.job_posting_id == job_id,
            Application.status == "reviewing",
        )
    )
    application = result.scalar_one_or_none()
    if not application:
        return RedirectResponse(f"/apply/{job_id}/status", status_code=303)

    job_result = await db.execute(
        select(JobPosting, Organization.name.label("org_name"))
        .outerjoin(Organization, JobPosting.organization_id == Organization.id)
        .where(JobPosting.id == job_id)
    )
    row = job_result.first()
    job = row[0] if row else None
    org_name = row[1] if row else None

    ctx = await _ctx(request, db, user,
                     application=application, job=job, org_name=org_name)
    return templates.TemplateResponse("apply/review.html", ctx)


@router.post("/apply/{job_id}/approve")
async def approve_application(
    request: Request,
    job_id: str,
    user: User = Depends(require_user),
    db: AsyncSession = Depends(get_db),
    csrf_token: str = Form(""),
):
    """Approve generated documents and proceed to form filling."""
    if not validate_csrf_token(request, csrf_token):
        return RedirectResponse(f"/apply/{job_id}/review", status_code=303)

    result = await db.execute(
        select(Application).where(
            Application.user_id == user.id,
            Application.job_posting_id == job_id,
            Application.status == "reviewing",
        )
    )
    application = result.scalar_one_or_none()
    if not application:
        return RedirectResponse(f"/apply/{job_id}/status", status_code=303)

    application.user_approved = True
    await db.commit()

    # Dispatch form filling task (after commit)
    from app.tasks.apply_tasks import fill_application
    fill_application.delay(str(application.id))

    return RedirectResponse(f"/apply/{job_id}/status", status_code=303)


@router.get("/apply/{job_id}/preview", response_class=HTMLResponse)
async def preview_page(
    request: Request,
    job_id: str,
    user: User = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    """Preview filled form screenshots before final submit."""
    result = await db.execute(
        select(Application).where(
            Application.user_id == user.id,
            Application.job_posting_id == job_id,
            Application.status == "filling",
        )
    )
    application = result.scalar_one_or_none()
    if not application:
        return RedirectResponse(f"/apply/{job_id}/status", status_code=303)

    ctx = await _ctx(request, db, user, application=application)
    return templates.TemplateResponse("apply/preview.html", ctx)


@router.post("/apply/{job_id}/submit")
async def submit_application(
    request: Request,
    job_id: str,
    user: User = Depends(require_user),
    db: AsyncSession = Depends(get_db),
    csrf_token: str = Form(""),
):
    """Final submission confirmation."""
    if not validate_csrf_token(request, csrf_token):
        return RedirectResponse(f"/apply/{job_id}/preview", status_code=303)

    result = await db.execute(
        select(Application).where(
            Application.user_id == user.id,
            Application.job_posting_id == job_id,
            Application.status == "filling",
        )
    )
    application = result.scalar_one_or_none()
    if not application:
        return RedirectResponse(f"/apply/{job_id}/status", status_code=303)

    from app.tasks.apply_tasks import submit_application as submit_task
    submit_task.delay(str(application.id))

    return RedirectResponse(f"/apply/{job_id}/status", status_code=303)


@router.post("/apply/{job_id}/retry")
async def retry_application(
    request: Request,
    job_id: str,
    user: User = Depends(require_user),
    db: AsyncSession = Depends(get_db),
    csrf_token: str = Form(""),
):
    """Retry a failed application from the failed step."""
    if not validate_csrf_token(request, csrf_token):
        return RedirectResponse(f"/apply/{job_id}/status", status_code=303)

    result = await db.execute(
        select(Application).where(
            Application.user_id == user.id,
            Application.job_posting_id == job_id,
            Application.status == "failed",
        ).order_by(Application.created_at.desc())
    )
    application = result.scalar_one_or_none()
    if not application:
        return RedirectResponse(f"/apply/{job_id}/status", status_code=303)

    error_step = application.error_step
    application.error_message = None
    application.error_step = None

    # Re-dispatch from the failed step
    from app.tasks import apply_tasks

    if error_step in ("extraction", None):
        application.status = "pending"
    elif error_step in ("generation", "ai_validation", "formatting"):
        application.status = "extracting"
    elif error_step in ("form_fill", "job_removed"):
        application.status = "reviewing"
        application.user_approved = True
    elif error_step == "submission":
        application.status = "filling"

    await db.commit()

    # Dispatch after commit so Celery can find the updated row
    if error_step in ("extraction", None):
        apply_tasks.extract_job_details.delay(str(application.id))
    elif error_step in ("generation", "ai_validation", "formatting"):
        apply_tasks.generate_documents.delay(str(application.id))
    elif error_step in ("form_fill", "job_removed"):
        apply_tasks.fill_application.delay(str(application.id))
    elif error_step == "submission":
        apply_tasks.submit_application.delay(str(application.id))

    return RedirectResponse(f"/apply/{job_id}/status", status_code=303)


# --- Application History ---

@router.get("/applications", response_class=HTMLResponse)
async def application_history(
    request: Request,
    user: User = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    """List all user applications."""
    result = await db.execute(
        select(Application, JobPosting.title, Organization.name.label("org_name"))
        .outerjoin(JobPosting, Application.job_posting_id == JobPosting.id)
        .outerjoin(Organization, JobPosting.organization_id == Organization.id)
        .where(Application.user_id == user.id)
        .order_by(Application.created_at.desc())
    )
    applications = []
    for row in result:
        applications.append({
            "application": row[0],
            "job_title": row[1],
            "org_name": row[2],
        })

    ctx = await _ctx(request, db, user, applications=applications)
    return templates.TemplateResponse("apply/history.html", ctx)
