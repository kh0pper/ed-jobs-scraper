"""Seed applicant profile from master resume markdown.

Parses the markdown resume into structured JSONB fields and
attaches to the first user in the database.

Usage:
    docker compose exec backend python -m scripts.seed_applicant_profile

Env vars:
    MASTER_RESUME_PATH - Path to master resume markdown (default: /app/data/master-resume.md)
    APPLICANT_USER_EMAIL - Email of user to attach to (default: first user in DB)
"""

import os
import re
import sys
from pathlib import Path

# Handle Docker vs host path resolution
if os.path.isdir("/app/app"):
    sys.path.insert(0, "/app")
else:
    sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))

from sqlalchemy import select
from app.models.base import SyncSessionLocal
from app.models.user import User
from app.models.applicant_profile import ApplicantProfile

# Import ALL models for relationship resolution
from app.models.organization import Organization  # noqa: F401
from app.models.scrape_source import ScrapeSource  # noqa: F401
from app.models.scrape_run import ScrapeRun  # noqa: F401
from app.models.job_posting import JobPosting  # noqa: F401
from app.models.district_demographics import DistrictDemographics  # noqa: F401
from app.models.application import Application  # noqa: F401
from app.models.digest_preference import DigestPreference  # noqa: F401
from app.models.saved_job import SavedJob  # noqa: F401
from app.models.user_interaction import UserInteraction  # noqa: F401
from app.models.user_interest_profile import UserInterestProfile  # noqa: F401


def parse_master_resume(text: str) -> dict:
    """Parse master resume markdown into structured fields."""
    sections = {}
    current_section = None
    current_lines = []

    for line in text.split("\n"):
        stripped = line.strip()
        if stripped.startswith("## "):
            if current_section:
                sections[current_section] = "\n".join(current_lines)
            current_section = stripped[3:].strip()
            current_lines = []
        elif current_section:
            current_lines.append(line)
        elif stripped.startswith("# "):
            sections["_name"] = stripped[2:].strip()
        elif "|" in stripped and ("@" in stripped or "linkedin" in stripped):
            sections["_contact"] = stripped

    if current_section:
        sections[current_section] = "\n".join(current_lines)

    return sections


def parse_contact(contact_line: str) -> dict:
    """Parse contact line: 'City, ST | (xxx) xxx-xxxx | email | linkedin'"""
    parts = [p.strip() for p in contact_line.split("|")]
    result = {}

    for part in parts:
        if "@" in part:
            result["email"] = part
        elif "linkedin" in part.lower():
            url = part if part.startswith("http") else f"https://{part}"
            result["linkedin_url"] = url
        elif re.match(r"\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}", part):
            result["phone"] = part
        elif "," in part:
            city_state = part.split(",")
            result["city"] = city_state[0].strip()
            result["state"] = city_state[1].strip() if len(city_state) > 1 else ""

    return result


def parse_education(text: str) -> list[dict]:
    """Parse education section into structured entries."""
    entries = []
    current = None

    for line in text.split("\n"):
        stripped = line.strip()
        if not stripped or stripped == "---":
            continue

        if stripped.startswith("**"):
            # Degree line: **Degree, Field**
            if current:
                entries.append(current)
            clean = stripped.replace("**", "")
            # Split on first comma for degree vs field
            parts = clean.split(",", 1)
            current = {
                "degree": parts[0].strip(),
                "field": parts[1].strip() if len(parts) > 1 else "",
                "institution": "",
                "city": "",
                "state": "",
                "graduation_date": "",
                "details": "",
            }
        elif current and not stripped.startswith("- "):
            # Institution line: University Name, City, ST | Date
            parts = stripped.split("|")
            loc = parts[0].strip()
            date = parts[1].strip() if len(parts) > 1 else ""

            # Parse "University Name, City, ST"
            loc_parts = loc.rsplit(",", 2)
            if len(loc_parts) >= 3:
                current["institution"] = loc_parts[0].strip()
                current["city"] = loc_parts[1].strip()
                current["state"] = loc_parts[2].strip()
            elif len(loc_parts) == 2:
                current["institution"] = loc_parts[0].strip()
                current["state"] = loc_parts[1].strip()
            else:
                current["institution"] = loc.strip()

            current["graduation_date"] = date
        elif current and stripped.startswith("- "):
            bullet = stripped[2:].strip()
            if current["details"]:
                current["details"] += "\n" + bullet
            else:
                current["details"] = bullet

    if current:
        entries.append(current)

    return entries


def parse_certifications(text: str) -> list[dict]:
    """Parse certifications section."""
    certs = []
    for line in text.split("\n"):
        stripped = line.strip()
        if stripped.startswith("- "):
            clean = stripped[2:].replace("**", "")
            # Format: "Name — Issuer (status)"
            parts = clean.split("—", 1)
            name = parts[0].strip()
            rest = parts[1].strip() if len(parts) > 1 else ""

            status = ""
            paren_match = re.search(r"\(([^)]+)\)", rest)
            if paren_match:
                status = paren_match.group(1)
                rest = rest[:paren_match.start()].strip()

            certs.append({
                "name": name,
                "issuer": rest,
                "status": status,
                "date": "",
            })

    return certs


def parse_work_history(text: str) -> list[dict]:
    """Parse work history into structured entries."""
    entries = []
    current = None

    for line in text.split("\n"):
        stripped = line.strip()
        if not stripped or stripped == "---":
            continue

        if stripped.startswith("### "):
            # New position
            if current:
                entries.append(current)
            title = stripped[4:].strip()
            current = {
                "title": title,
                "organization": "",
                "city": "",
                "state": "",
                "start_date": "",
                "end_date": "",
                "current": False,
                "bullets": [],
            }
        elif current and stripped.startswith("**") and not stripped.startswith("- "):
            # Org info line: **Org, Department** | City, ST | Dates
            clean = stripped.replace("**", "")
            parts = [p.strip() for p in clean.split("|")]

            if len(parts) >= 3:
                current["organization"] = parts[0]
                # Parse city, state from second part
                loc = parts[1]
                loc_parts = loc.rsplit(",", 1)
                current["city"] = loc_parts[0].strip()
                current["state"] = loc_parts[1].strip() if len(loc_parts) > 1 else ""
                # Parse dates
                dates = parts[2]
                date_parts = dates.split("–")
                current["start_date"] = date_parts[0].strip()
                current["end_date"] = date_parts[1].strip() if len(date_parts) > 1 else ""
                current["current"] = "present" in current["end_date"].lower()
            elif len(parts) == 2:
                current["organization"] = parts[0]
                current["end_date"] = parts[1]
        elif current and stripped.startswith("- "):
            current["bullets"].append(stripped[2:].strip())

    if current:
        entries.append(current)

    return entries


def parse_skills(text: str) -> dict:
    """Parse skills section into {category: [skill1, ...]}."""
    skills = {}
    for line in text.split("\n"):
        stripped = line.strip()
        if stripped.startswith("**"):
            clean = stripped.replace("**", "")
            parts = clean.split(":", 1)
            if len(parts) == 2:
                category = parts[0].strip()
                items = [s.strip() for s in parts[1].split(",")]
                skills[category] = items
    return skills


def parse_languages(text: str) -> list[dict]:
    """Parse languages section."""
    languages = []
    for line in text.split("\n"):
        stripped = line.strip()
        if stripped.startswith("- "):
            clean = stripped[2:]
            # Format: "Working knowledge of Spanish and French (details)"
            if "Spanish" in clean:
                languages.append({"language": "Spanish", "proficiency": "working knowledge"})
            if "French" in clean:
                languages.append({"language": "French", "proficiency": "working knowledge"})
    return languages


def main():
    resume_path = os.environ.get("MASTER_RESUME_PATH", "/app/data/master-resume.md")

    # Also check notes/ directory as fallback
    if not os.path.exists(resume_path):
        alt_paths = [
            "/app/notes/master-resume.md",
            str(Path(__file__).parent.parent / "notes" / "master-resume.md"),
        ]
        for alt in alt_paths:
            if os.path.exists(alt):
                resume_path = alt
                break

    if not os.path.exists(resume_path):
        print(f"ERROR: Resume not found at {resume_path}")
        print("Set MASTER_RESUME_PATH env var or place master-resume.md in data/")
        sys.exit(1)

    text = Path(resume_path).read_text()
    sections = parse_master_resume(text)

    print(f"Parsed sections: {list(sections.keys())}")

    # Parse contact info
    contact = parse_contact(sections.get("_contact", ""))
    full_name = sections.get("_name", "")

    # Parse structured data
    education = parse_education(sections.get("Education", ""))
    certifications = parse_certifications(sections.get("Certifications & Credentials", ""))
    work_history = parse_work_history(sections.get("Professional Experience", ""))
    skills = parse_skills(sections.get("Technical Skills", ""))
    languages = parse_languages(sections.get("Languages", ""))

    print(f"  Name: {full_name}")
    print(f"  Contact: {contact}")
    print(f"  Education: {len(education)} entries")
    print(f"  Certifications: {len(certifications)} entries")
    print(f"  Work History: {len(work_history)} entries")
    print(f"  Skills: {len(skills)} categories")
    print(f"  Languages: {len(languages)} entries")

    # Database
    session = SyncSessionLocal()
    try:
        # Find target user
        user_email = os.environ.get("APPLICANT_USER_EMAIL")
        if user_email:
            user = session.execute(
                select(User).where(User.email == user_email)
            ).scalar_one_or_none()
        else:
            user = session.execute(
                select(User).order_by(User.created_at).limit(1)
            ).scalar_one_or_none()

        if not user:
            print("ERROR: No user found in database")
            sys.exit(1)

        print(f"\nAttaching profile to user: {user.email}")

        # Upsert profile
        profile = session.execute(
            select(ApplicantProfile).where(ApplicantProfile.user_id == user.id)
        ).scalar_one_or_none()

        if not profile:
            profile = ApplicantProfile(user_id=user.id)
            session.add(profile)

        profile.full_name = full_name
        profile.email = contact.get("email", "")
        profile.phone = contact.get("phone", "")
        profile.city = contact.get("city", "")
        profile.state = contact.get("state", "")
        profile.linkedin_url = contact.get("linkedin_url", "")

        profile.education = education
        profile.certifications = certifications
        profile.work_history = work_history
        profile.skills = skills
        profile.languages = languages

        profile.master_resume_md = text

        session.commit()
        print("Profile saved successfully!")

    finally:
        session.close()


if __name__ == "__main__":
    main()
