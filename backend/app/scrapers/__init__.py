"""Scraper package — import all scrapers to trigger @register_scraper decorators."""

from app.scrapers.applitrack import ApplitrackScraper  # noqa: F401
from app.scrapers.schoolspring import SchoolSpringScraper  # noqa: F401
from app.scrapers.eightfold import EightfoldScraper  # noqa: F401
from app.scrapers.taleo import TaleoScraper  # noqa: F401
from app.scrapers.smartrecruiters import SmartRecruitersScraper  # noqa: F401
from app.scrapers.jobvite import JobviteScraper  # noqa: F401
from app.scrapers.ttcportals import TtcPortalsScraper  # noqa: F401
from app.scrapers.munis import MunisScraper  # noqa: F401
from app.scrapers.workday import WorkdayScraper  # noqa: F401
from app.scrapers.simple_career import SimpleCareerScraper  # noqa: F401
