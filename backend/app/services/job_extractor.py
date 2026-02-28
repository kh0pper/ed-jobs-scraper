"""Job detail extraction — per-platform strategies.

Lazy extraction: called on-demand when user clicks Easy Apply.
Results cached to job_postings.description to avoid re-extraction.
"""

import io
import logging
import re
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# Shared httpx client for simple HTML fetches
_http_client: httpx.Client | None = None

# Pattern to extract HTML content from Applitrack Output.asp JavaScript response.
# The response wraps HTML in JS function calls that inject content into the DOM.
_APPLITRACK_JS_HTML_PATTERN = re.compile(
    r"document\.write\('(.*?)'\);", re.DOTALL
)


def _get_http_client() -> httpx.Client:
    global _http_client
    if _http_client is None:
        _http_client = httpx.Client(
            timeout=httpx.Timeout(connect=10, read=30, write=10, pool=10),
            follow_redirects=True,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
            },
        )
    return _http_client


def extract_job_details(job_posting) -> dict:
    """Extract full job details based on platform.

    Args:
        job_posting: JobPosting ORM object with platform, application_url, description, etc.

    Returns:
        dict with keys: description, requirements, qualifications, salary_info
        Any key may be None if not available.
    """
    # If description already cached, return it
    if job_posting.description:
        return {
            "description": job_posting.description,
            "requirements": job_posting.requirements,
            "qualifications": None,
            "salary_info": job_posting.salary_text,
        }

    platform = job_posting.platform
    extractor = EXTRACTORS.get(platform)
    if not extractor:
        logger.warning("No extractor for platform: %s", platform)
        return {"description": None, "requirements": None, "qualifications": None, "salary_info": None}

    try:
        result = extractor(job_posting)
        logger.info("Extracted details for %s job: %s", platform, job_posting.title[:60])
        return result
    except Exception as e:
        logger.error("Failed to extract details for %s (%s): %s", platform, job_posting.application_url, e)
        return {"description": None, "requirements": None, "qualifications": None, "salary_info": None}


# --- Applitrack helpers ---

def _applitrack_output_url(application_url: str) -> str:
    """Derive the Output.asp URL from an Applitrack application URL.

    Applitrack detail pages load content dynamically via JavaScript from
    jobpostings/Output.asp. The detail page HTML itself is just a shell.
    We fetch Output.asp directly to get the actual job content.
    """
    parsed = urlparse(application_url)
    # URL like: /humbleisd/onlineapp/default.aspx?AppliTrackJobId=11814&...
    # Output URL: /humbleisd/onlineapp/jobpostings/Output.asp?same params
    base_path = parsed.path.rsplit("/", 1)[0]  # /humbleisd/onlineapp
    output_path = f"{base_path}/jobpostings/Output.asp"
    return f"{parsed.scheme}://{parsed.netloc}{output_path}?{parsed.query}"


def _applitrack_parse_js_response(js_content: str) -> BeautifulSoup:
    """Extract HTML from Applitrack Output.asp JavaScript response.

    The response is JavaScript that injects HTML into the page via DOM
    manipulation calls. We extract the HTML strings and parse them.
    """
    writes = _APPLITRACK_JS_HTML_PATTERN.findall(js_content)
    html = "".join(w.replace("\\'", "'") for w in writes)
    return BeautifulSoup(html, "html.parser")


def _applitrack_extract_pdf_text(url: str) -> str | None:
    """Download a PDF attachment from Applitrack and extract text.

    Applitrack serves all attachments as PDF regardless of the original
    filename extension (.doc, .docx, .pdf all come back as application/pdf).
    """
    try:
        from pypdf import PdfReader
    except ImportError:
        logger.warning("pypdf not installed — cannot extract PDF attachment text")
        return None

    client = _get_http_client()
    try:
        resp = client.get(url)
        resp.raise_for_status()
    except httpx.HTTPError as e:
        logger.warning("Failed to download Applitrack attachment %s: %s", url, e)
        return None

    try:
        reader = PdfReader(io.BytesIO(resp.content))
        pages = []
        for page in reader.pages:
            text = page.extract_text()
            if text:
                pages.append(text.strip())
        return "\n\n".join(pages) if pages else None
    except Exception as e:
        logger.warning("Failed to parse PDF from %s: %s", url, e)
        return None


# --- Platform-specific extractors ---

def _extract_applitrack(job) -> dict:
    """Applitrack: fetch Output.asp for actual job content.

    Applitrack detail pages are a shell that loads content via JS from
    jobpostings/Output.asp. The Output.asp response contains:
    - Structured fields in <li> elements (Position Type, Date Posted, etc.)
    - Inline description text in <span class='normal'> outside <li> elements
    - Attachment links (PDFs) in <div class='AppliTrackJobPostingAttachments'>

    Some districts embed the full job description inline; others put it
    in an attached PDF/doc file (served as PDF by Applitrack).
    """
    output_url = _applitrack_output_url(job.application_url)
    client = _get_http_client()
    resp = client.get(output_url)
    resp.raise_for_status()

    soup = _applitrack_parse_js_response(resp.text)

    # 1. Extract structured fields from <li> elements
    fields = {}
    for li in soup.find_all("li"):
        label_span = li.find("span", class_="label")
        if not label_span:
            continue
        label = label_span.get_text(strip=True).rstrip(":")
        values = [n.get_text(strip=True) for n in li.find_all("span", class_="normal")]
        if values:
            fields[label] = " / ".join(v for v in values if v)

    # 2. Extract inline description from <span class='normal'> outside <li> elements
    inline_parts = []
    main_div = soup.find("div", style=re.compile(r"position:\s*relative"))
    if main_div:
        for span in main_div.find_all("span", class_="normal", recursive=False):
            text = span.get_text(separator="\n", strip=True)
            if len(text) > 20:
                inline_parts.append(text)

    # 3. Extract attachment text
    attachment_text = None
    attachments_div = soup.find("div", class_="AppliTrackJobPostingAttachments")
    if attachments_div:
        for link in attachments_div.find_all("a", href=True):
            href = link["href"]
            if "BrowseFile" in href:
                logger.info("Downloading Applitrack attachment: %s", link.get_text(strip=True))
                text = _applitrack_extract_pdf_text(href)
                if text:
                    attachment_text = text
                    break  # Usually just one main attachment

    # 4. Extract salary info from structured fields or inline content
    salary_info = None
    for key in ("Salary", "Compensation", "Pay"):
        if key in fields:
            salary_info = fields.pop(key)
            break

    if not salary_info and inline_parts:
        for part in inline_parts:
            if re.search(r"\$[\d,]+", part) and len(part) < 200:
                salary_info = part
                break

    # 5. Build description — prefer attachment text over inline
    description_parts = []

    # Add structured fields as a header
    field_lines = []
    for key, val in fields.items():
        if key not in ("Position Type",):  # Skip redundant fields
            field_lines.append(f"{key}: {val}")
    if field_lines:
        description_parts.append("\n".join(field_lines))

    # Add inline description or attachment text
    if attachment_text:
        description_parts.append(attachment_text)
    elif inline_parts:
        description_parts.append("\n\n".join(inline_parts))

    description = "\n\n".join(description_parts) if description_parts else None

    return {
        "description": description,
        "requirements": None,
        "qualifications": None,
        "salary_info": salary_info,
    }


def _extract_eightfold(job) -> dict:
    """Eightfold: description already in DB from scraper."""
    return {
        "description": job.description,
        "requirements": job.requirements,
        "qualifications": None,
        "salary_info": job.salary_text,
    }


def _extract_smartrecruiters(job) -> dict:
    """SmartRecruiters: fetch detail from API endpoint."""
    # Extract posting ID from URL
    url = job.application_url
    client = _get_http_client()

    # SmartRecruiters detail pages are HTML with structured content
    resp = client.get(url)
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "lxml")

    description = None
    requirements = None

    # SmartRecruiters uses semantic HTML sections
    for section in soup.select(".job-section, .jobdetails, [class*='description']"):
        heading = section.find(["h2", "h3", "h4"])
        text = section.get_text(separator="\n", strip=True)
        if heading:
            heading_text = heading.get_text(strip=True).lower()
            if "requirement" in heading_text or "qualification" in heading_text:
                requirements = text
                continue
        if len(text) > 50:
            description = (description or "") + "\n\n" + text

    return {
        "description": description,
        "requirements": requirements,
        "qualifications": None,
        "salary_info": None,
    }


def _extract_browser_page(job) -> dict:
    """Generic browser extraction for SPA/JS-heavy platforms.

    Used by: SchoolSpring, Jobvite, TTC Portals, Taleo.
    """
    import asyncio
    from app.scrapers.browser import get_browser

    async def _fetch():
        async with get_browser() as browser:
            page = await browser.new_page()
            try:
                await page.goto(job.application_url, wait_until="domcontentloaded", timeout=30000)
                await browser.apply_stealth(page)

                # Wait for content to load
                await page.wait_for_timeout(3000)

                # Extract main content via DOM query
                content = await page.evaluate("""() => {
                    const selectors = [
                        '.job-description', '.jobDescription', '#job-description',
                        '[class*="description"]', '[class*="details"]',
                        '.posting-details', '.job-details', '.content-wrapper',
                        'article', 'main',
                    ];
                    for (const sel of selectors) {
                        const el = document.querySelector(sel);
                        if (el && el.innerText.length > 100) {
                            return el.innerText;
                        }
                    }
                    return document.body.innerText;
                }""")

                return content
            finally:
                await page.close()

    text = asyncio.run(_fetch())

    return {
        "description": text if text and len(text) > 50 else None,
        "requirements": None,
        "qualifications": None,
        "salary_info": None,
    }


def _extract_simple_html(job) -> dict:
    """Simple HTML extraction for static pages (Munis, Simple Career)."""
    client = _get_http_client()
    resp = client.get(job.application_url)
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "lxml")

    # Remove navigation/footer noise
    for tag in soup.find_all(["script", "style", "nav", "header", "footer"]):
        tag.decompose()

    # Try common content containers
    for selector in [".job-description", ".content", "main", "article", "#content"]:
        el = soup.select_one(selector)
        if el:
            text = el.get_text(separator="\n", strip=True)
            if len(text) > 100:
                return {
                    "description": text,
                    "requirements": None,
                    "qualifications": None,
                    "salary_info": None,
                }

    # Fallback: body text
    body = soup.find("body")
    text = body.get_text(separator="\n", strip=True) if body else None

    return {
        "description": text if text and len(text) > 100 else None,
        "requirements": None,
        "qualifications": None,
        "salary_info": None,
    }


def _extract_workday(job) -> dict:
    """Workday: JSON API for job details."""
    # Workday job URLs contain the job ID; the detail API endpoint returns full description
    client = _get_http_client()
    resp = client.get(job.application_url)
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "lxml")

    description = None
    # Workday renders description in data-automation-id tagged divs
    for div in soup.select("[data-automation-id='jobPostingDescription'], .css-cygeeu, [class*='jobDescription']"):
        text = div.get_text(separator="\n", strip=True)
        if len(text) > 50:
            description = (description or "") + "\n\n" + text

    if not description:
        # Fallback to generic extraction
        return _extract_simple_html(job)

    return {
        "description": description,
        "requirements": None,
        "qualifications": None,
        "salary_info": None,
    }


# Platform -> extractor function mapping
EXTRACTORS = {
    "applitrack": _extract_applitrack,
    "eightfold": _extract_eightfold,
    "smartrecruiters": _extract_smartrecruiters,
    "schoolspring": _extract_browser_page,
    "jobvite": _extract_browser_page,
    "ttcportals": _extract_browser_page,
    "taleo": _extract_browser_page,
    "workday": _extract_workday,
    "munis": _extract_simple_html,
    "simple_career": _extract_simple_html,
}
