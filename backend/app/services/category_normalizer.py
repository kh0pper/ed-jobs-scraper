"""Category normalization service for job postings."""

import re
from typing import Final

# Standardized job categories
CATEGORIES: Final[list[str]] = [
    "Teacher",
    "Administrator",
    "Instructional Support",
    "Counselor",
    "Special Education",
    "Paraprofessional",
    "Office/Clerical",
    "Food Service",
    "Transportation",
    "Custodial/Maintenance",
    "Technology",
    "Health Services",
    "Security",
    "Athletics/Coaching",
    "Other",
]

# Keywords to category mapping (order matters - first match wins)
CATEGORY_PATTERNS: Final[list[tuple[str, list[str]]]] = [
    # Administrators
    ("Administrator", [
        r"\bprincipal\b",
        r"\bassistant principal\b",
        r"\bdirector\b",
        r"\bsuperintendent\b",
        r"\bdean\b",
        r"\bchief\b",
        r"\bexecutive\b",
        r"\bvp\b",
        r"\bvice president\b",
        r"\bcampus leader\b",
        r"\bhead of school\b",
        r"\bmanager\b",
        r"\bcoordinator\b(?!.*instructional)",
    ]),

    # Special Education (before general Teacher)
    ("Special Education", [
        r"\bspecial education\b",
        r"\bsped\b",
        r"\bspecial ed\b",
        r"\blife skills\b",
        r"\bbehavior specialist\b",
        r"\bdiagnostician\b",
        r"\bautism\b",
        r"\bada\b.*\bspecialist\b",
        r"\binclusion\b",
        r"\bcontent mastery\b",
        r"\bself[-\s]?contained\b",
        r"\bresource\b.*\bteacher\b",
        r"\bard\s+facilitator\b",
        r"\bintervention\s+specialist\b",
        r"\b504\s+coordinator\b",
        r"\biep\b",
    ]),

    # Counselors
    ("Counselor", [
        r"\bcounselor\b",
        r"\bcounseling\b",
        r"\bguidance\b",
        r"\bsocial worker\b",
        r"\bpsychologist\b",
        r"\blicensed specialist\b",
        r"\blssp\b",
        r"\blpc\b",
    ]),

    # Health Services
    ("Health Services", [
        r"\bnurse\b",
        r"\brn\b",
        r"\blvn\b",
        r"\bhealth\s+services\b",
        r"\bschool health\b",
        r"\bclinic\b",
        r"\bmedical\b",
        r"\bspeech.{0,5}language.{0,5}pathologist\b",
        r"\bslp\b",
        r"\bspeech.{0,5}pathologist\b",
        r"\bspeech.{0,5}therapist\b",
        r"\boccupational\s+therapist\b",
        r"\bot\b.*\btherapist\b",
        r"\bphysical\s+therapist\b",
        r"\bpt\b.*\btherapist\b",
        r"\basha\b",
    ]),

    # Instructional Support (before Teacher)
    ("Instructional Support", [
        r"\binstructional\s+coach\b",
        r"\bcurriculum\b",
        r"\binstructional\s+specialist\b",
        r"\bliteracy\s+coach\b",
        r"\bmath\s+coach\b",
        r"\breading\s+specialist\b",
        r"\binterventionist\b",
        r"\binstructional\s+coordinator\b",
        r"\blibrarian\b",
        r"\bmedia specialist\b",
        r"\binstructional\s+facilitator\b",
    ]),

    # Teachers
    ("Teacher", [
        r"\bteacher\b",
        r"\binstructor\b",
        r"\beducator\b",
        r"\bfaculty\b",
        r"\bprofessor\b",
        r"\blecturer\b",
        r"\btutor\b",
        r"\bela\b",
        r"\benglish\b.*\barts\b",
        r"\bmath\s+\d",
        r"\bscience\b.*\bgrade\b",
        r"\bsocial studies\b",
        r"\bhistory\b.*\bteach",
        r"\bpre[-\s]?k\b",
        r"\bkindergarten\b",
        r"\belementary\b.*\bgeneral",
        r"\bgrade\s+\d",
        r"\bsubject\b.*\barea\b",
        r"\bcertified\b.*\bposition\b",
    ]),

    # Paraprofessionals
    ("Paraprofessional", [
        r"\bparaprofessional\b",
        r"\bpara\b",
        r"\bparaeducator\b",
        r"\baide\b",
        r"\bassistant\b(?!.*principal)(?!.*director)(?!.*manager)",
        r"\binstructional\s+aide\b",
        r"\bteacher\s+aide\b",
        r"\bclassroom\s+assistant\b",
    ]),

    # Technology
    ("Technology", [
        r"\btechnology\b",
        r"\btechnician\b",
        r"\bit\s+support\b",
        r"\bnetwork\b",
        r"\bcomputer\b",
        r"\bsystems\b",
        r"\bdata\s+specialist\b",
        r"\bhelpdesk\b",
        r"\bsoftware\b",
        r"\bdeveloper\b",
        r"\bengineer\b",
    ]),

    # Athletics/Coaching
    ("Athletics/Coaching", [
        r"\bcoach\b",
        r"\bathletic\b",
        r"\bsports\b",
        r"\bfootball\b",
        r"\bbasketball\b",
        r"\bvolleyball\b",
        r"\bsoccer\b",
        r"\btrack\b",
        r"\bswimming\b",
        r"\btennis\b",
        r"\bgolf\b",
        r"\bcheer\b",
        r"\bband director\b",
        r"\borchestra\b",
        r"\bfine arts\b",
        r"\bdrama\b",
    ]),

    # Office/Clerical
    ("Office/Clerical", [
        r"\bsecretary\b",
        r"\bclerical\b",
        r"\breceptionist\b",
        r"\boffice\b.*\bassistant\b",
        r"\badministrative\b(?!.*assistant principal)",
        r"\bdata entry\b",
        r"\bregistrar\b",
        r"\battendance\b.*\bclerk\b",
        r"\baccounts\b",
        r"\bpayroll\b",
        r"\bhr\b",
        r"\bhuman resources\b",
        r"\bbookkeeper\b",
        r"\bfinance\b",
    ]),

    # Food Service
    ("Food Service", [
        r"\bfood service\b",
        r"\bcafeteria\b",
        r"\bkitchen\b",
        r"\bcook\b",
        r"\bnutrition\b",
        r"\bchild nutrition\b",
        r"\bbreakfast\b.*\bprogram\b",
        r"\blunch\b.*\bprogram\b",
    ]),

    # Transportation
    ("Transportation", [
        r"\bbus\s+driver\b",
        r"\bbus\s+drivers\b",
        r"\btransportation\b",
        r"\bdriver\b",
        r"\broute\b.*\bmanager\b",
        r"\bfleet\b",
        r"\bmechanic\b",
    ]),

    # Custodial/Maintenance
    ("Custodial/Maintenance", [
        r"\bcustodian\b",
        r"\bjanitor\b",
        r"\bmaintenance\b",
        r"\bgroundskeeper\b",
        r"\bgrounds\s*(wo)?man\b",
        r"\bgrounds\s+worker\b",
        r"\bfacilities\b",
        r"\boperations\b",
        r"\bhvac\b",
        r"\belectrician\b",
        r"\bplumber\b",
        r"\bcleaning\b",
        r"\bpainter\b",
        r"\bcarpenter\b",
        r"\bwarehouse\b",
    ]),

    # Security
    ("Security", [
        r"\bsecurity\b",
        r"\bpolice\b",
        r"\bofficer\b(?!.*loan)",
        r"\bsro\b",
        r"\bresource officer\b",
        r"\bcrossing guard\b",
        r"\bmonitor\b",
        r"\bnoon\s+duty\b",
        r"\blunch\s+duty\b",
        r"\bplayground\b.*\bsupervisor\b",
        r"\bcampus\s+aide\b",
        r"\bsafety\s+advocate\b",
    ]),
]


def normalize_category(title: str | None, raw_category: str | None = None) -> str | None:
    """
    Normalize a job posting to a standard category.

    Args:
        title: The job title
        raw_category: Optional raw category from the source platform

    Returns:
        Normalized category string or None if no match
    """
    if not title and not raw_category:
        return None

    # Combine title and raw_category for matching
    text = " ".join(filter(None, [title, raw_category])).lower()

    for category, patterns in CATEGORY_PATTERNS:
        for pattern in patterns:
            if re.search(pattern, text, re.IGNORECASE):
                return category

    return "Other"


def normalize_category_bulk(jobs: list[dict]) -> list[dict]:
    """
    Normalize categories for multiple jobs.

    Args:
        jobs: List of job dicts with 'title' and optionally 'raw_category'

    Returns:
        Same list with 'category' field added/updated
    """
    for job in jobs:
        job["category"] = normalize_category(
            job.get("title"),
            job.get("raw_category"),
        )
    return jobs


def get_all_categories() -> list[str]:
    """Return list of all valid normalized categories."""
    return CATEGORIES.copy()
