#!/usr/bin/env python3
"""
Format Google Docs resumes to match Kevin's master resume style.

Uses the Google Docs API batchUpdate to apply:
- Bookman Old Style font throughout
- Specific sizes: name (22pt), contact (11pt), section headers (12pt), body (10pt)
- Bold/italic patterns for job titles, degrees, etc.
- Tab-aligned dates (right tab stop at right margin)
- Native bullet lists
- 36pt (0.5") margins, single line spacing

Usage:
    /home/kh0pp/spring-2026/canvas-companion/.venv/bin/python3 scripts/format_resume_docs.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path.home() / "spring-2026" / "canvas-companion"))

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

# --- Constants ---
FONT = "Bookman Old Style"
CREDENTIALS_DIR = Path.home() / "spring-2026" / "canvas-companion" / "config"
DOC_IDS = {
    "master": "1oBnVDHXVMiQh4IPWIiFP92_c2rsK3jCKhC7BIXxMupg",
    "ap_resume": "1zZb3LgvmZLnoi60aGKXRT-FNntOWvnEt7rapQ3DH40w",
    "ap_cover": "1W4V7Jv-zT-SXASbPcoKe0aVphf48cZkytn4TAs_dZ-s",
}

NOTES_DIR = Path(__file__).parent.parent / "notes"


def get_docs_service():
    """Authenticate and return Google Docs API service."""
    token_file = CREDENTIALS_DIR / "google_token.json"
    creds = Credentials.from_authorized_user_file(
        str(token_file),
        ["https://www.googleapis.com/auth/drive",
         "https://www.googleapis.com/auth/documents"],
    )
    if creds.expired and creds.refresh_token:
        from google.auth.transport.requests import Request
        creds.refresh(Request())
    return build("docs", "v1", credentials=creds)


def utf16_len(text):
    """Google Docs API counts positions in UTF-16 code units."""
    return len(text.encode("utf-16-le")) // 2


def clear_document(service, doc_id):
    """Delete all content from a Google Doc."""
    doc = service.documents().get(documentId=doc_id).execute()
    body_content = doc.get("body", {}).get("content", [])
    end_index = 1
    for element in body_content:
        if "endIndex" in element:
            end_index = max(end_index, element["endIndex"])
    if end_index > 2:
        service.documents().batchUpdate(
            documentId=doc_id,
            body={"requests": [{
                "deleteContentRange": {
                    "range": {"startIndex": 1, "endIndex": end_index - 1}
                }
            }]},
        ).execute()


def set_margins(service, doc_id):
    """Set 36pt (0.5 inch) margins on all sides."""
    service.documents().batchUpdate(
        documentId=doc_id,
        body={"requests": [{
            "updateDocumentStyle": {
                "documentStyle": {
                    "marginTop": {"magnitude": 36, "unit": "PT"},
                    "marginBottom": {"magnitude": 36, "unit": "PT"},
                    "marginLeft": {"magnitude": 36, "unit": "PT"},
                    "marginRight": {"magnitude": 36, "unit": "PT"},
                },
                "fields": "marginTop,marginBottom,marginLeft,marginRight",
            }
        }]},
    ).execute()


# --- Helpers ---

def find_bold_spans(md_text):
    """
    Find bold span positions in markdown text, relative to the cleaned (no **) text.
    Returns list of (start, end) tuples.
    """
    spans = []
    clean_pos = 0
    md_pos = 0
    in_bold = False
    bold_start = 0

    while md_pos < len(md_text):
        if md_text[md_pos:md_pos + 2] == "**":
            if in_bold:
                spans.append((bold_start, clean_pos))
                in_bold = False
            else:
                bold_start = clean_pos
                in_bold = True
            md_pos += 2
        else:
            clean_pos += 1
            md_pos += 1
    return spans


def is_experience_section(name):
    return "experience" in name.lower() or "employment" in name.lower()


def is_education_section(name):
    return "education" in name.lower()


def is_skills_section(name):
    return "skill" in name.lower()


def is_research_section(name):
    return "research" in name.lower()


# --- Markdown Parser ---

def parse_resume(md_path):
    """
    Parse resume markdown into segments: (type, content).
    Types: name, contact, section_header, org_role (H3), bold_line,
           bullet, sub_bullet, body
    """
    text = md_path.read_text()
    lines = text.split("\n")
    segments = []

    for line in lines:
        stripped = line.strip()
        if stripped == "---" or not stripped:
            continue
        if stripped.startswith("# ") and not stripped.startswith("## "):
            segments.append(("name", stripped[2:]))
        elif "|" in stripped and ("@" in stripped or "linkedin" in stripped):
            segments.append(("contact", stripped))
        elif stripped.startswith("## "):
            segments.append(("section_header", stripped[3:]))
        elif stripped.startswith("### "):
            segments.append(("org_role", stripped[4:]))
        elif line.startswith("  - ") or line.startswith("  -\t"):
            segments.append(("sub_bullet", stripped[2:]))
        elif stripped.startswith("- "):
            segments.append(("bullet", stripped[2:]))
        elif stripped.startswith("**"):
            segments.append(("bold_line", stripped))
        else:
            segments.append(("body", stripped))
    return segments


def parse_cover_letter(md_path):
    """Parse cover letter markdown into segments."""
    text = md_path.read_text()
    lines = text.split("\n")
    segments = []

    for line in lines:
        stripped = line.strip()
        if stripped == "---" or not stripped:
            continue
        if stripped.startswith("# ") and not stripped.startswith("## "):
            segments.append(("name", stripped[2:]))
        elif "|" in stripped and ("@" in stripped or "linkedin" in stripped):
            segments.append(("contact", stripped))
        else:
            segments.append(("cl_body", stripped))
    return segments


# --- Output Item Builder ---
# Each output item: (text_to_insert, style_dict)
# style_dict keys:
#   size (pt), bold, italic, bullet, sub_bullet,
#   border_bottom, section_header, space_above (pt),
#   bold_spans [(start,end)...], bold_before_colon


def build_resume_items(segments):
    """Convert parsed segments into output items with formatting metadata."""
    items = []
    current_section = None
    i = 0

    while i < len(segments):
        seg_type, content = segments[i]

        if seg_type == "name":
            items.append((content + "\n", {"bold": True, "size": 22}))

        elif seg_type == "contact":
            items.append((content + "\n", {"size": 11, "border_bottom": True}))

        elif seg_type == "section_header":
            current_section = content
            items.append((content.upper() + "\n", {
                "bold": True, "size": 12, "section_header": True, "space_above": 6,
            }))

        elif seg_type == "org_role":
            if is_experience_section(current_section or ""):
                title = content
                # Check if next segment is a bold_line (org info)
                if i + 1 < len(segments) and segments[i + 1][0] == "bold_line":
                    org_md = segments[i + 1][1]
                    org_clean = org_md.replace("**", "")
                    parts = [p.strip() for p in org_clean.split("|")]

                    # Swap order: org line first, then title line
                    if len(parts) >= 3:
                        # OrgName | Location | Dates
                        org_text = parts[0] + " | " + parts[2] + "\n"
                        title_text = title + " | " + parts[1] + "\n"
                    elif len(parts) == 2:
                        org_text = parts[0] + " | " + parts[1] + "\n"
                        title_text = title + "\n"
                    else:
                        org_text = org_clean + "\n"
                        title_text = title + "\n"

                    items.append((org_text, {"space_above": 4}))
                    items.append((title_text, {
                        "bold": True, "italic": True,
                    }))
                    i += 2
                    continue
                else:
                    items.append((title + "\n", {
                        "bold": True, "italic": True, "space_above": 4,
                    }))

            elif is_research_section(current_section or ""):
                # H3 with pipe-separated: Title | University | Dates
                parts = [p.strip() for p in content.split("|")]
                if len(parts) >= 3:
                    items.append((parts[0] + " | " + parts[2] + "\n", {
                        "bold": True, "space_above": 4,
                    }))
                    items.append((parts[1] + "\n", {}))
                elif len(parts) == 2:
                    items.append((parts[0] + " | " + parts[1] + "\n", {
                        "bold": True, "space_above": 4,
                    }))
                else:
                    items.append((content + "\n", {"bold": True, "space_above": 4}))
            else:
                items.append((content + "\n", {"space_above": 4}))

        elif seg_type == "bold_line":
            # Bold_line NOT consumed by org_role lookahead
            clean = content.replace("**", "")

            if is_experience_section(current_section or ""):
                # Sub-role title: **Title** | Dates
                # Keep pipe separators as-is
                items.append((clean + "\n", {
                    "bold": True, "italic": True,
                }))

            elif is_education_section(current_section or ""):
                items.append((clean + "\n", {"bold": True, "space_above": 4}))

            elif is_skills_section(current_section or ""):
                # **Label**: rest
                items.append((clean + "\n", {"bold_before_colon": True}))

            else:
                # Generic: apply bold spans from markdown
                bold_spans = find_bold_spans(content)
                items.append((clean + "\n", {"bold_spans": bold_spans}))

        elif seg_type == "bullet":
            clean = content.replace("**", "")
            bold_spans = find_bold_spans(content)
            style = {"bullet": True}
            if bold_spans:
                style["bold_spans"] = bold_spans
            items.append((clean + "\n", style))

        elif seg_type == "sub_bullet":
            clean = content.replace("**", "")
            items.append((clean + "\n", {"sub_bullet": True}))

        elif seg_type == "body":
            items.append((content + "\n", {}))

        i += 1

    return items


def build_cover_letter_items(segments):
    """Convert parsed cover letter segments into output items."""
    items = []
    for seg_type, content in segments:
        if seg_type == "name":
            items.append((content + "\n", {"bold": True, "size": 22}))
        elif seg_type == "contact":
            items.append((content + "\n", {"size": 11, "border_bottom": True}))
        elif seg_type == "cl_body":
            items.append((content + "\n", {"cl_body": True}))
    return items


# --- Google Docs Request Builder ---

def items_to_requests(items, default_size=10, default_spacing=100):
    """
    Convert output items to Google Docs API batchUpdate requests.

    Returns list of requests ready for batchUpdate.
    """
    # Phase 1: Build full text and track positions
    text_parts = []
    positions = []  # (start, end, style_dict)
    pos = 1  # Google Docs indices start at 1

    for text, style in items:
        start = pos
        text_parts.append(text)
        length = utf16_len(text)
        end = start + length
        positions.append((start, end, style))
        pos = end

    full_text = "".join(text_parts)
    total_end = 1 + utf16_len(full_text)

    requests = []

    # 1. Insert all text at once
    requests.append({
        "insertText": {
            "location": {"index": 1},
            "text": full_text,
        }
    })

    # 2. Set default font + size for entire document
    requests.append({
        "updateTextStyle": {
            "range": {"startIndex": 1, "endIndex": total_end},
            "textStyle": {
                "weightedFontFamily": {"fontFamily": FONT},
                "fontSize": {"magnitude": default_size, "unit": "PT"},
            },
            "fields": "weightedFontFamily,fontSize",
        }
    })

    # 3. Set default paragraph spacing for everything
    requests.append({
        "updateParagraphStyle": {
            "range": {"startIndex": 1, "endIndex": total_end},
            "paragraphStyle": {
                "lineSpacing": default_spacing,
                "spaceAbove": {"magnitude": 0, "unit": "PT"},
                "spaceBelow": {"magnitude": 0, "unit": "PT"},
            },
            "fields": "lineSpacing,spaceAbove,spaceBelow",
        }
    })

    # 4. Per-item formatting
    for start, end, style in positions:
        text_end = end - 1  # Exclude trailing \n for text styles

        # --- Text styles ---
        ts_fields = []
        ts_style = {}

        if style.get("bold"):
            ts_style["bold"] = True
            ts_fields.append("bold")
        if style.get("italic"):
            ts_style["italic"] = True
            ts_fields.append("italic")
        if style.get("size"):
            ts_style["fontSize"] = {"magnitude": style["size"], "unit": "PT"}
            ts_fields.append("fontSize")

        if ts_fields:
            requests.append({
                "updateTextStyle": {
                    "range": {"startIndex": start, "endIndex": text_end},
                    "textStyle": ts_style,
                    "fields": ",".join(ts_fields),
                }
            })

        # --- Bold spans (for bullets/lines with inline bold) ---
        if style.get("bold_spans"):
            # Get the actual inserted text (without trailing \n)
            inserted_text = full_text[start - 1:end - 1 - 1]  # -1 for 0-indexed, -1 for \n
            for span_start, span_end in style["bold_spans"]:
                # Convert character positions to UTF-16 positions
                abs_start = start + utf16_len(inserted_text[:span_start])
                abs_end = start + utf16_len(inserted_text[:span_end])
                requests.append({
                    "updateTextStyle": {
                        "range": {"startIndex": abs_start, "endIndex": abs_end},
                        "textStyle": {"bold": True},
                        "fields": "bold",
                    }
                })

        # --- Bold before colon (Technical Skills) ---
        if style.get("bold_before_colon"):
            inserted_text = full_text[start - 1:end - 1 - 1]
            colon_pos = inserted_text.find(":")
            if colon_pos > 0:
                colon_abs = start + utf16_len(inserted_text[:colon_pos])
                requests.append({
                    "updateTextStyle": {
                        "range": {"startIndex": start, "endIndex": colon_abs},
                        "textStyle": {"bold": True},
                        "fields": "bold",
                    }
                })

        # --- Paragraph styles ---
        ps_fields = []
        ps_style = {}

        if style.get("space_above"):
            ps_style["spaceAbove"] = {
                "magnitude": style["space_above"], "unit": "PT"
            }
            ps_fields.append("spaceAbove")

        if style.get("border_bottom") or style.get("section_header"):
            width = 0.5
            padding = 3 if style.get("border_bottom") else 1
            ps_style["borderBottom"] = {
                "color": {"color": {"rgbColor": {"red": 0, "green": 0, "blue": 0}}},
                "width": {"magnitude": width, "unit": "PT"},
                "padding": {"magnitude": padding, "unit": "PT"},
                "dashStyle": "SOLID",
            }
            ps_fields.append("borderBottom")

        if ps_fields:
            requests.append({
                "updateParagraphStyle": {
                    "range": {"startIndex": start, "endIndex": end},
                    "paragraphStyle": ps_style,
                    "fields": ",".join(ps_fields),
                }
            })

        # --- Bullets ---
        if style.get("bullet"):
            requests.append({
                "createParagraphBullets": {
                    "range": {"startIndex": start, "endIndex": end},
                    "bulletPreset": "BULLET_DISC_CIRCLE_SQUARE",
                }
            })

        if style.get("sub_bullet"):
            requests.append({
                "createParagraphBullets": {
                    "range": {"startIndex": start, "endIndex": end},
                    "bulletPreset": "BULLET_DISC_CIRCLE_SQUARE",
                }
            })
            # Increase nesting level for sub-bullets
            requests.append({
                "updateParagraphStyle": {
                    "range": {"startIndex": start, "endIndex": end},
                    "paragraphStyle": {
                        "indentStart": {"magnitude": 36, "unit": "PT"},
                        "indentFirstLine": {"magnitude": 18, "unit": "PT"},
                    },
                    "fields": "indentStart,indentFirstLine",
                }
            })

        # --- Cover letter body paragraph spacing ---
        if style.get("cl_body"):
            requests.append({
                "updateParagraphStyle": {
                    "range": {"startIndex": start, "endIndex": end},
                    "paragraphStyle": {
                        "spaceAbove": {"magnitude": 6, "unit": "PT"},
                    },
                    "fields": "spaceAbove",
                }
            })

    return requests


# --- Main ---

def format_document(service, doc_id, items, default_size=10, default_spacing=100):
    """Clear a document and apply formatted content."""
    print(f"  Clearing document...")
    clear_document(service, doc_id)

    print(f"  Setting margins...")
    set_margins(service, doc_id)

    print(f"  Building formatting requests...")
    requests = items_to_requests(items, default_size, default_spacing)

    print(f"  Sending {len(requests)} requests to Google Docs API...")
    service.documents().batchUpdate(
        documentId=doc_id,
        body={"requests": requests},
    ).execute()
    print(f"  Done!")


def main():
    service = get_docs_service()

    # --- Master Resume ---
    print("\n=== Master Resume ===")
    segments = parse_resume(NOTES_DIR / "master-resume.md")
    items = build_resume_items(segments)
    print(f"  {len(segments)} segments → {len(items)} output items")
    format_document(service, DOC_IDS["master"], items)

    # --- AP Resume ---
    print("\n=== AP Resume ===")
    segments = parse_resume(NOTES_DIR / "ap-resume.md")
    items = build_resume_items(segments)
    print(f"  {len(segments)} segments → {len(items)} output items")
    format_document(service, DOC_IDS["ap_resume"], items)

    # --- AP Cover Letter ---
    print("\n=== AP Cover Letter ===")
    segments = parse_cover_letter(NOTES_DIR / "ap-cover-letter.md")
    items = build_cover_letter_items(segments)
    print(f"  {len(segments)} segments → {len(items)} output items")
    format_document(service, DOC_IDS["ap_cover"], items, default_size=11, default_spacing=115)

    print("\nAll documents formatted successfully!")
    print("Open them to verify:")
    for name, doc_id in DOC_IDS.items():
        print(f"  {name}: https://docs.google.com/document/d/{doc_id}/edit")


if __name__ == "__main__":
    main()
