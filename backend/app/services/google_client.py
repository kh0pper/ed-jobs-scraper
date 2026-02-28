"""Google Docs/Drive client for creating and exporting documents.

Sync-only — called from Celery tasks.
Per-user OAuth tokens from applicant_profiles.google_token_json (encrypted).
"""

import json
import logging

from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

from app.services.crypto import decrypt
from app.services.resume_formatter import format_to_google_doc

logger = logging.getLogger(__name__)


def get_google_services(encrypted_token_json: str) -> tuple:
    """Build Google Docs + Drive services from encrypted token.

    Args:
        encrypted_token_json: Encrypted JSON token from applicant_profiles

    Returns:
        (docs_service, drive_service)

    Raises:
        ValueError: If token is expired and can't be refreshed
    """
    token_data = json.loads(decrypt(encrypted_token_json))

    creds = Credentials(
        token=token_data["token"],
        refresh_token=token_data.get("refresh_token"),
        token_uri=token_data.get("token_uri", "https://oauth2.googleapis.com/token"),
        client_id=token_data.get("client_id"),
        client_secret=token_data.get("client_secret"),
        scopes=token_data.get("scopes", []),
    )

    if creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            logger.info("Refreshed expired Google OAuth token")
        except Exception as e:
            logger.error("Failed to refresh Google token: %s", e)
            raise ValueError("Google token expired and refresh failed") from e

    docs_service = build("docs", "v1", credentials=creds)
    drive_service = build("drive", "v3", credentials=creds)

    return docs_service, drive_service


def create_doc(drive_service, title: str, folder_id: str | None = None) -> str:
    """Create a new Google Doc and return its ID."""
    metadata = {
        "name": title,
        "mimeType": "application/vnd.google-apps.document",
    }
    if folder_id:
        metadata["parents"] = [folder_id]

    doc = drive_service.files().create(body=metadata, fields="id").execute()
    doc_id = doc["id"]
    logger.info("Created Google Doc: %s (%s)", title, doc_id)
    return doc_id


def format_and_export(
    docs_service,
    drive_service,
    doc_id: str,
    markdown: str,
    doc_type: str = "resume",
) -> bytes:
    """Format a Google Doc from markdown and export as PDF.

    Args:
        docs_service: Google Docs API service
        drive_service: Google Drive API service
        doc_id: Google Doc ID
        markdown: Content in markdown format
        doc_type: "resume" or "cover_letter"

    Returns:
        PDF bytes
    """
    # Format the document
    format_to_google_doc(docs_service, doc_id, markdown, doc_type)

    # Export as PDF
    pdf_bytes = drive_service.files().export(
        fileId=doc_id,
        mimeType="application/pdf",
    ).execute()

    logger.info("Exported %s as PDF (%d bytes)", doc_id, len(pdf_bytes))
    return pdf_bytes


def markdown_to_pdf_weasyprint(markdown: str, doc_type: str = "resume") -> bytes:
    """Local PDF generation fallback using WeasyPrint.

    Used when Google API is unavailable.
    """
    import weasyprint

    # Convert markdown to basic HTML
    html_lines = ['<html><head><style>']

    # CSS styling to match Bookman Old Style formatting
    html_lines.append("""
        @page { margin: 0.5in; size: letter; }
        body {
            font-family: 'Bookman Old Style', 'Palatino Linotype', Georgia, serif;
            font-size: 10pt;
            line-height: 1.15;
            color: #000;
        }
        h1 { font-size: 22pt; font-weight: bold; margin: 0 0 2pt 0; }
        h2 {
            font-size: 12pt; font-weight: bold; text-transform: uppercase;
            border-bottom: 0.5pt solid #000; padding-bottom: 1pt;
            margin: 6pt 0 2pt 0;
        }
        h3 { font-size: 10pt; font-weight: bold; font-style: italic; margin: 4pt 0 0 0; }
        p { margin: 0 0 2pt 0; }
        .contact { font-size: 11pt; border-bottom: 0.5pt solid #000; padding-bottom: 3pt; margin-bottom: 4pt; }
        ul { margin: 0; padding-left: 18pt; }
        li { margin: 0; }
        .cl-body { font-size: 11pt; line-height: 1.3; margin: 6pt 0; }
    """)

    html_lines.append('</style></head><body>')

    # Simple markdown to HTML conversion
    in_list = False
    for line in markdown.split("\n"):
        stripped = line.strip()
        if not stripped or stripped == "---":
            if in_list:
                html_lines.append("</ul>")
                in_list = False
            continue

        if stripped.startswith("# ") and not stripped.startswith("## "):
            if in_list:
                html_lines.append("</ul>")
                in_list = False
            html_lines.append(f"<h1>{_md_inline(stripped[2:])}</h1>")
        elif stripped.startswith("## "):
            if in_list:
                html_lines.append("</ul>")
                in_list = False
            html_lines.append(f"<h2>{_md_inline(stripped[3:])}</h2>")
        elif stripped.startswith("### "):
            if in_list:
                html_lines.append("</ul>")
                in_list = False
            html_lines.append(f"<h3>{_md_inline(stripped[4:])}</h3>")
        elif stripped.startswith("- "):
            if not in_list:
                html_lines.append("<ul>")
                in_list = True
            html_lines.append(f"<li>{_md_inline(stripped[2:])}</li>")
        elif "|" in stripped and ("@" in stripped or "linkedin" in stripped):
            if in_list:
                html_lines.append("</ul>")
                in_list = False
            html_lines.append(f'<p class="contact">{_md_inline(stripped)}</p>')
        else:
            if in_list:
                html_lines.append("</ul>")
                in_list = False
            css_class = ' class="cl-body"' if doc_type == "cover_letter" else ""
            html_lines.append(f"<p{css_class}>{_md_inline(stripped)}</p>")

    if in_list:
        html_lines.append("</ul>")

    html_lines.append("</body></html>")
    html_content = "\n".join(html_lines)

    pdf_bytes = weasyprint.HTML(string=html_content).write_pdf()
    logger.info("Generated PDF via WeasyPrint (%d bytes)", len(pdf_bytes))
    return pdf_bytes


def _md_inline(text: str) -> str:
    """Convert inline markdown (bold) to HTML."""
    import re
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    return text
