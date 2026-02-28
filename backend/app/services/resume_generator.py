"""AI-powered resume and cover letter generation via Z.ai.

Generates tailored documents based on applicant profile, job posting, and org info.
"""

import logging
import re

from app.services.zai_client import get_zai_client

logger = logging.getLogger(__name__)

RESUME_SYSTEM_PROMPT = """You are an expert resume writer specializing in Texas K-12 education careers.
You create tailored, ATS-optimized resumes in markdown format.

FORMATTING RULES:
- Use markdown: # for name, ## for section headers, ### for job titles
- Use **bold** for organization names, degree names, certification names
- Use | to separate location and dates on org info lines
- Use - for bullet points
- Keep it to 1-2 pages equivalent
- Use Bookman Old Style font conventions (the formatter handles actual styling)

STRUCTURE:
# [Full Name]
[City, ST | Phone | Email | LinkedIn]
---
## Professional Summary
[2-3 sentences tailored to this specific job]
---
## Education
[Most relevant degrees]
---
## Certifications & Credentials
[Most relevant certifications]
---
## Professional Experience
[Most relevant positions with tailored bullets]
---
## Technical Skills
[Relevant skills grouped by category]

TAILORING RULES:
- Reorder sections to prioritize what's most relevant to this job
- Adjust bullet points to emphasize transferable skills
- Match keywords from the job description
- Quantify achievements where possible
- Remove irrelevant experience or condense it
- Never fabricate experience — only reframe existing experience
"""

COVER_LETTER_SYSTEM_PROMPT = """You are an expert cover letter writer for Texas K-12 education careers.
Write professional, compelling cover letters that:
- Address the specific job and organization
- Connect the applicant's experience to the role's requirements
- Show knowledge of the district/organization
- Are warm but professional in tone
- Are 3-4 paragraphs (about 300-400 words)

FORMAT (markdown):
# [Full Name]
[City, ST | Phone | Email | LinkedIn]
---
[Date]

[Hiring Manager/Committee]
[Organization Name]

Dear Hiring Committee,

[Body paragraphs]

Sincerely,
[Full Name]
"""


def generate_tailored_resume(
    profile,
    job_posting,
    organization=None,
    demographics=None,
) -> tuple[str, dict]:
    """Generate a tailored resume for a specific job.

    Args:
        profile: ApplicantProfile ORM object
        job_posting: JobPosting ORM object (with description)
        organization: Organization ORM object (optional)
        demographics: dict with district demographics (optional)

    Returns:
        (resume_markdown, usage_dict)
    """
    client = get_zai_client()

    prompt_parts = [
        "Generate a tailored resume for this job application.",
        "",
        "=== MASTER RESUME ===",
        profile.master_resume_md or "(No master resume available)",
        "",
        "=== TARGET JOB ===",
        f"Title: {job_posting.title}",
        f"Organization: {organization.name if organization else 'Unknown'}",
        f"Platform: {job_posting.platform}",
        f"Location: {job_posting.city or ''}, {job_posting.state or 'TX'}",
    ]

    if job_posting.category:
        prompt_parts.append(f"Category: {job_posting.category}")

    if job_posting.description:
        prompt_parts.extend(["", "Job Description:", job_posting.description[:3000]])

    if job_posting.requirements:
        prompt_parts.extend(["", "Requirements:", job_posting.requirements[:2000]])

    if organization:
        prompt_parts.extend([
            "",
            "=== ORGANIZATION INFO ===",
            f"Name: {organization.name}",
            f"Type: {organization.org_type or 'ISD'}",
            f"Region: ESC {organization.esc_region or 'unknown'}",
            f"County: {organization.county or 'unknown'}",
        ])

    if demographics:
        prompt_parts.extend([
            "",
            "=== DISTRICT DEMOGRAPHICS ===",
            f"Economically Disadvantaged: {demographics.get('economically_disadvantaged', 'N/A')}%",
            f"At-Risk: {demographics.get('at_risk', 'N/A')}%",
            f"ELL: {demographics.get('ell', 'N/A')}%",
            f"Special Education: {demographics.get('special_ed', 'N/A')}%",
        ])

    prompt_parts.extend([
        "",
        "Generate the tailored resume in markdown format following the structure rules above.",
        "Output ONLY the resume markdown, no commentary.",
    ])

    prompt = "\n".join(prompt_parts)

    response = client.complete_complex(
        prompt=prompt,
        system_prompt=RESUME_SYSTEM_PROMPT,
        temperature=0.6,
        max_tokens=4096,
    )

    return response.content, response.usage


def generate_cover_letter(
    profile,
    job_posting,
    organization=None,
    demographics=None,
) -> tuple[str, dict]:
    """Generate a tailored cover letter for a specific job.

    Returns:
        (cover_letter_markdown, usage_dict)
    """
    client = get_zai_client()

    prompt_parts = [
        "Generate a tailored cover letter for this job application.",
        "",
        "=== APPLICANT ===",
        f"Name: {profile.full_name}",
        f"Current Role: {profile.work_history[0]['title'] if profile.work_history else 'N/A'}",
        f"Location: {profile.city or ''}, {profile.state or 'TX'}",
        "",
        f"=== MASTER RESUME (for background) ===",
        profile.master_resume_md or "(No master resume)",
        "",
        "=== TARGET JOB ===",
        f"Title: {job_posting.title}",
        f"Organization: {organization.name if organization else 'Unknown'}",
        f"Location: {job_posting.city or ''}, {job_posting.state or 'TX'}",
    ]

    if job_posting.description:
        prompt_parts.extend(["", "Job Description:", job_posting.description[:3000]])

    if organization:
        prompt_parts.extend([
            "",
            f"District Type: {organization.org_type or 'ISD'}",
            f"ESC Region: {organization.esc_region or ''}",
        ])

    if demographics:
        prompt_parts.extend([
            "",
            "District Demographics:",
            f"  Economically Disadvantaged: {demographics.get('economically_disadvantaged', 'N/A')}%",
            f"  At-Risk: {demographics.get('at_risk', 'N/A')}%",
        ])

    prompt_parts.extend([
        "",
        "Generate the cover letter in markdown format.",
        "Output ONLY the cover letter markdown, no commentary.",
    ])

    prompt = "\n".join(prompt_parts)

    response = client.complete_complex(
        prompt=prompt,
        system_prompt=COVER_LETTER_SYSTEM_PROMPT,
        temperature=0.7,
        max_tokens=2048,
    )

    return response.content, response.usage


def validate_resume_markdown(text: str) -> bool:
    """Validate that generated text looks like a resume, not an error."""
    if not text or len(text) < 100:
        return False
    if not re.search(r"^#{1,3}\s", text, re.MULTILINE):
        return False
    if not re.search(r"^- ", text, re.MULTILINE):
        return False
    # Check it's not an AI refusal
    refusal_patterns = ["I cannot", "I'm unable", "I apologize", "As an AI"]
    if any(p.lower() in text[:200].lower() for p in refusal_patterns):
        return False
    return True
