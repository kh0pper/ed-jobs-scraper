"""Seed known scrape sources for manually-identified organizations.

Adds scrape_source entries for organizations whose job posting platforms
we already know (HISD/Eightfold, KIPP/SmartRecruiters, etc.) and creates
organizations for non-TEA entities (nonprofits, associations, companies).

Usage:
    docker compose exec backend python -m scripts.seed_known_sources
"""

import uuid

from app.config import get_settings
from app.models.base import SyncSessionLocal
from app.models.organization import Organization
from app.models.scrape_source import ScrapeSource
from app.models.job_posting import JobPosting  # noqa: F401 — needed for relationship resolution
from app.models.scrape_run import ScrapeRun  # noqa: F401

settings = get_settings()

# Known district-to-platform mappings (TEA ID -> platform config)
# These are districts already in the organizations table from TEA seed
KNOWN_DISTRICT_SOURCES = [
    {
        "tea_id": "101912",  # Houston ISD
        "platform": "eightfold",
        "base_url": "https://apply.houstonisd.org/careers",
        "slug": "houstonisd",
    },
    {
        "tea_id": "101913",  # Humble ISD
        "platform": "applitrack",
        "base_url": "https://www.applitrack.com/humbleisd/onlineapp/default.aspx?all=1",
        "slug": "humbleisd",
    },
    {
        "tea_id": "101919",  # Spring ISD
        "platform": "schoolspring",
        "base_url": "https://springisd.schoolspring.com/",
        "slug": "springisd",
    },
]

# Non-TEA organizations (nonprofits, associations, state agencies, etc.)
# These need to be created in organizations table first, then get sources
NON_TEA_ORGS = [
    # State agency
    {
        "name": "Texas Education Agency",
        "slug": "tea",
        "org_type": "state_agency",
        "city": "Austin",
        "website_url": "https://tea.texas.gov",
        "sources": [
            {
                "platform": "taleo",
                "base_url": "https://capps.taleo.net/careersection/701/jobsearch.ftl",
                "slug": "tea-capps",
            }
        ],
    },
    # Charter networks (with known platforms)
    {
        "name": "KIPP Texas Public Schools",
        "slug": "kipp-texas",
        "org_type": "charter",
        "city": "Houston",
        "website_url": "https://www.kipptexas.org",
        "sources": [
            {
                "platform": "smartrecruiters",
                "base_url": "https://careers.smartrecruiters.com/KIPP/texas-ads",
                "slug": "kipp-texas",
            }
        ],
    },
    {
        "name": "YES Prep Public Schools",
        "slug": "yes-prep",
        "org_type": "charter",
        "city": "Houston",
        "website_url": "https://www.yesprep.org",
        "sources": [
            {
                "platform": "ttcportals",
                "base_url": "https://yesprepcareers.ttcportals.com/search/jobs",
                "slug": "yesprep",
            }
        ],
    },
    {
        "name": "IDEA Public Schools",
        "slug": "idea-public-schools",
        "org_type": "charter",
        "city": "Weslaco",
        "website_url": "https://www.ideapublicschools.org",
        "sources": [
            {
                "platform": "jobvite",
                "base_url": "https://jobs.jobvite.com/ideapublicschools-english/jobs",
                "slug": "ideapublicschools",
            }
        ],
    },
    {
        "name": "Harmony Public Schools",
        "slug": "harmony-public-schools",
        "org_type": "charter",
        "city": "Houston",
        "website_url": "https://www.harmonytx.org",
        "sources": [
            {
                "platform": "munis",
                "base_url": "https://harmonypublicschoolstxemployees.munisselfservice.com/employmentopportunities/default.aspx",
                "slug": "harmonypublicschools",
            }
        ],
    },
    {
        "name": "Uplift Education",
        "slug": "uplift-education",
        "org_type": "charter",
        "city": "Dallas",
        "website_url": "https://www.uplifteducation.org",
        "sources": [
            {
                "platform": "applitrack",
                "base_url": "https://www.applitrack.com/uplifteducation/onlineapp/default.aspx?all=1",
                "slug": "uplifteducation",
            }
        ],
    },
    # Nonprofits
    {
        "name": "Teach For America",
        "slug": "teach-for-america",
        "org_type": "nonprofit",
        "city": "Houston",
        "website_url": "https://www.teachforamerica.org",
        "sources": [
            {
                "platform": "workday",
                "base_url": "https://teachforamerica.wd1.myworkdayjobs.com/TFA_Careers",
                "slug": "teachforamerica",
            }
        ],
    },
    {
        "name": "IDRA",
        "slug": "idra",
        "org_type": "nonprofit",
        "city": "San Antonio",
        "website_url": "https://www.idra.org",
        "sources": [
            {
                "platform": "simple_career",
                "base_url": "https://idra.org/who-we-are/employment/",
                "slug": "idra",
            }
        ],
    },
    {
        "name": "Commit Partnership",
        "slug": "commit-partnership",
        "org_type": "nonprofit",
        "city": "Dallas",
        "website_url": "https://commitpartnership.org",
        "sources": [
            {
                "platform": "simple_career",
                "base_url": "https://commitpartnership.org/about/careers",
                "slug": "commitpartnership",
            }
        ],
    },
    {
        "name": "Raise Your Hand Texas",
        "slug": "raise-your-hand-texas",
        "org_type": "nonprofit",
        "city": "Austin",
        "website_url": "https://www.raiseyourhandtexas.org",
        "sources": [
            {
                "platform": "simple_career",
                "base_url": "https://www.raiseyourhandtexas.org/about/careers/",
                "slug": "raiseyourhandtexas",
            }
        ],
    },
    {
        "name": "E3 Alliance",
        "slug": "e3-alliance",
        "org_type": "nonprofit",
        "city": "Austin",
        "website_url": "https://e3alliance.org",
        "sources": [
            {
                "platform": "simple_career",
                "base_url": "https://e3alliance.org/about/careers/",
                "slug": "e3alliance",
            }
        ],
    },
    {
        "name": "Children at Risk",
        "slug": "children-at-risk",
        "org_type": "nonprofit",
        "city": "Houston",
        "website_url": "https://childrenatrisk.org",
        "sources": [
            {
                "platform": "simple_career",
                "base_url": "https://childrenatrisk.org/jobs/",
                "slug": "childrenatrisk",
            }
        ],
    },
    {
        "name": "Texas Appleseed",
        "slug": "texas-appleseed",
        "org_type": "nonprofit",
        "city": "Austin",
        "website_url": "https://www.texasappleseed.org",
        "sources": [
            {
                "platform": "simple_career",
                "base_url": "https://www.texasappleseed.org/careers",
                "slug": "texasappleseed",
            }
        ],
    },
    {
        "name": "TNTP",
        "slug": "tntp",
        "org_type": "nonprofit",
        "city": "New York",
        "state": "NY",
        "website_url": "https://tntp.org",
        "sources": [
            {
                "platform": "simple_career",
                "base_url": "https://tntp.org/careers/",
                "slug": "tntp",
            }
        ],
    },
    {
        "name": "NMSI",
        "slug": "nmsi",
        "org_type": "nonprofit",
        "city": "Dallas",
        "website_url": "https://www.nms.org",
        "sources": [
            {
                "platform": "simple_career",
                "base_url": "https://www.nms.org/about-us/nmsi-careers",
                "slug": "nmsi",
            }
        ],
    },
    {
        "name": "Communities in Schools of Texas",
        "slug": "cis-texas",
        "org_type": "nonprofit",
        "city": "Austin",
        "website_url": "https://www.cisoftexas.org",
        "sources": [
            {
                "platform": "simple_career",
                "base_url": "https://www.cisoftexas.org/job-and-volunteer-opportunities/",
                "slug": "cistexas",
            }
        ],
    },
    {
        "name": "Texans Care for Children",
        "slug": "texans-care-for-children",
        "org_type": "nonprofit",
        "city": "Austin",
        "website_url": "https://txchildren.org",
        "sources": [
            {
                "platform": "simple_career",
                "base_url": "https://txchildren.org/work-with-us/",
                "slug": "texanscare",
            }
        ],
    },
    # Associations
    {
        "name": "Texas Association of School Boards",
        "slug": "tasb",
        "org_type": "association",
        "city": "Austin",
        "website_url": "https://www.tasb.org",
        "sources": [
            {
                "platform": "simple_career",
                "base_url": "https://www.tasb.org/about/careers",
                "slug": "tasb",
            }
        ],
    },
    # For-profit EdTech
    {
        "name": "Istation",
        "slug": "istation",
        "org_type": "for_profit",
        "city": "Dallas",
        "website_url": "https://www.istation.com",
        "sources": [
            {
                "platform": "simple_career",
                "base_url": "https://www.istation.com/careers",
                "slug": "istation",
            }
        ],
    },
]

# ESC regions as organizations (they post jobs too)
ESC_REGIONS = [
    {"name": "Education Service Center Region 20", "slug": "esc-region-20", "esc_region": 20, "city": "San Antonio",
     "sources": [{"platform": "applitrack", "base_url": "https://www.applitrack.com/esc20/onlineapp/default.aspx?all=1", "slug": "esc20"}]},
]


def seed():
    db = SyncSessionLocal()
    try:
        sources_created = 0
        orgs_created = 0

        # 1. Add sources for known TEA districts
        for entry in KNOWN_DISTRICT_SOURCES:
            org = db.query(Organization).filter(Organization.tea_id == entry["tea_id"]).first()
            if not org:
                print(f"  WARNING: TEA district {entry['tea_id']} not found — run seed_from_tea.py first")
                continue

            existing = db.query(ScrapeSource).filter(
                ScrapeSource.organization_id == org.id,
                ScrapeSource.platform == entry["platform"],
            ).first()
            if existing:
                print(f"  Skipped: {org.name} already has {entry['platform']} source")
                continue

            source = ScrapeSource(
                id=uuid.uuid4(),
                organization_id=org.id,
                platform=entry["platform"],
                base_url=entry["base_url"],
                slug=entry.get("slug"),
                discovered_by="manual",
            )
            db.add(source)
            org.platform_status = "mapped"
            sources_created += 1
            print(f"  Added: {org.name} -> {entry['platform']}")

        # 2. Create non-TEA orgs and their sources
        for org_data in NON_TEA_ORGS:
            existing = db.query(Organization).filter(Organization.slug == org_data["slug"]).first()
            if not existing:
                org = Organization(
                    id=uuid.uuid4(),
                    name=org_data["name"],
                    slug=org_data["slug"],
                    org_type=org_data["org_type"],
                    city=org_data.get("city"),
                    state=org_data.get("state", "TX"),
                    website_url=org_data.get("website_url"),
                    platform_status="mapped",
                )
                db.add(org)
                db.flush()
                orgs_created += 1
                print(f"  Created org: {org.name}")
            else:
                org = existing

            for src in org_data.get("sources", []):
                existing_src = db.query(ScrapeSource).filter(
                    ScrapeSource.organization_id == org.id,
                    ScrapeSource.platform == src["platform"],
                ).first()
                if existing_src:
                    continue

                source = ScrapeSource(
                    id=uuid.uuid4(),
                    organization_id=org.id,
                    platform=src["platform"],
                    base_url=src["base_url"],
                    slug=src.get("slug"),
                    discovered_by="manual",
                )
                db.add(source)
                sources_created += 1

        # 3. ESC regions
        for esc_data in ESC_REGIONS:
            existing = db.query(Organization).filter(Organization.slug == esc_data["slug"]).first()
            if not existing:
                org = Organization(
                    id=uuid.uuid4(),
                    name=esc_data["name"],
                    slug=esc_data["slug"],
                    org_type="esc",
                    esc_region=esc_data.get("esc_region"),
                    city=esc_data.get("city"),
                    state="TX",
                    platform_status="mapped",
                )
                db.add(org)
                db.flush()
                orgs_created += 1

            else:
                org = existing

            for src in esc_data.get("sources", []):
                existing_src = db.query(ScrapeSource).filter(
                    ScrapeSource.organization_id == org.id,
                    ScrapeSource.platform == src["platform"],
                ).first()
                if existing_src:
                    continue

                source = ScrapeSource(
                    id=uuid.uuid4(),
                    organization_id=org.id,
                    platform=src["platform"],
                    base_url=src["base_url"],
                    slug=src.get("slug"),
                    discovered_by="manual",
                )
                db.add(source)
                sources_created += 1

        db.commit()
        print(f"\nDone: {orgs_created} orgs created, {sources_created} sources created")

    except Exception as e:
        db.rollback()
        print(f"Error: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    seed()
