"""Resume/cover letter formatter for Google Docs.

Adapted from scripts/format_resume_docs.py — refactored into an
importable module for the Easy Apply pipeline.
"""

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

FONT = "Bookman Old Style"


def utf16_len(text: str) -> int:
    """Google Docs API counts positions in UTF-16 code units."""
    return len(text.encode("utf-16-le")) // 2


def find_bold_spans(md_text: str) -> list[tuple[int, int]]:
    """Find bold span positions in markdown, relative to cleaned text."""
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


def parse_resume(text: str) -> list[tuple[str, str]]:
    """Parse resume markdown into segments: (type, content)."""
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


def parse_cover_letter(text: str) -> list[tuple[str, str]]:
    """Parse cover letter markdown into segments."""
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


def _is_experience_section(name: str | None) -> bool:
    return name is not None and ("experience" in name.lower() or "employment" in name.lower())


def _is_education_section(name: str | None) -> bool:
    return name is not None and "education" in name.lower()


def _is_skills_section(name: str | None) -> bool:
    return name is not None and "skill" in name.lower()


def _is_research_section(name: str | None) -> bool:
    return name is not None and "research" in name.lower()


def build_resume_items(segments: list) -> list[tuple[str, dict]]:
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
            if _is_experience_section(current_section):
                title = content
                if i + 1 < len(segments) and segments[i + 1][0] == "bold_line":
                    org_md = segments[i + 1][1]
                    org_clean = org_md.replace("**", "")
                    parts = [p.strip() for p in org_clean.split("|")]
                    if len(parts) >= 3:
                        org_text = parts[0] + " | " + parts[2] + "\n"
                        title_text = title + " | " + parts[1] + "\n"
                    elif len(parts) == 2:
                        org_text = parts[0] + " | " + parts[1] + "\n"
                        title_text = title + "\n"
                    else:
                        org_text = org_clean + "\n"
                        title_text = title + "\n"
                    items.append((org_text, {"space_above": 4}))
                    items.append((title_text, {"bold": True, "italic": True}))
                    i += 2
                    continue
                else:
                    items.append((title + "\n", {"bold": True, "italic": True, "space_above": 4}))
            elif _is_research_section(current_section):
                parts = [p.strip() for p in content.split("|")]
                if len(parts) >= 3:
                    items.append((parts[0] + " | " + parts[2] + "\n", {"bold": True, "space_above": 4}))
                    items.append((parts[1] + "\n", {}))
                elif len(parts) == 2:
                    items.append((parts[0] + " | " + parts[1] + "\n", {"bold": True, "space_above": 4}))
                else:
                    items.append((content + "\n", {"bold": True, "space_above": 4}))
            else:
                items.append((content + "\n", {"space_above": 4}))
        elif seg_type == "bold_line":
            clean = content.replace("**", "")
            if _is_experience_section(current_section):
                items.append((clean + "\n", {"bold": True, "italic": True}))
            elif _is_education_section(current_section):
                items.append((clean + "\n", {"bold": True, "space_above": 4}))
            elif _is_skills_section(current_section):
                items.append((clean + "\n", {"bold_before_colon": True}))
            else:
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


def build_cover_letter_items(segments: list) -> list[tuple[str, dict]]:
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


def items_to_requests(items: list, default_size: int = 10, default_spacing: int = 100) -> list[dict]:
    """Convert output items to Google Docs API batchUpdate requests."""
    text_parts = []
    positions = []
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

    # Insert all text
    requests.append({
        "insertText": {"location": {"index": 1}, "text": full_text}
    })

    # Default font + size
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

    # Default paragraph spacing
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

    # Per-item formatting
    for start, end, style in positions:
        text_end = end - 1

        # Text styles
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

        # Bold spans
        if style.get("bold_spans"):
            inserted_text = full_text[start - 1:end - 2]
            for span_start, span_end in style["bold_spans"]:
                abs_start = start + utf16_len(inserted_text[:span_start])
                abs_end = start + utf16_len(inserted_text[:span_end])
                requests.append({
                    "updateTextStyle": {
                        "range": {"startIndex": abs_start, "endIndex": abs_end},
                        "textStyle": {"bold": True},
                        "fields": "bold",
                    }
                })

        # Bold before colon
        if style.get("bold_before_colon"):
            inserted_text = full_text[start - 1:end - 2]
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

        # Paragraph styles
        ps_fields = []
        ps_style = {}

        if style.get("space_above"):
            ps_style["spaceAbove"] = {"magnitude": style["space_above"], "unit": "PT"}
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

        # Bullets
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

        # Cover letter body spacing
        if style.get("cl_body"):
            requests.append({
                "updateParagraphStyle": {
                    "range": {"startIndex": start, "endIndex": end},
                    "paragraphStyle": {"spaceAbove": {"magnitude": 6, "unit": "PT"}},
                    "fields": "spaceAbove",
                }
            })

    return requests


def format_to_google_doc(docs_service, doc_id: str, markdown: str, doc_type: str = "resume"):
    """Full pipeline: clear doc → set margins → insert formatted content.

    Args:
        docs_service: Google Docs API service object
        doc_id: Google Doc ID
        markdown: Resume or cover letter in markdown format
        doc_type: "resume" or "cover_letter"
    """
    # Clear existing content
    doc = docs_service.documents().get(documentId=doc_id).execute()
    body_content = doc.get("body", {}).get("content", [])
    end_index = 1
    for element in body_content:
        if "endIndex" in element:
            end_index = max(end_index, element["endIndex"])
    if end_index > 2:
        docs_service.documents().batchUpdate(
            documentId=doc_id,
            body={"requests": [{"deleteContentRange": {"range": {"startIndex": 1, "endIndex": end_index - 1}}}]},
        ).execute()

    # Set margins
    docs_service.documents().batchUpdate(
        documentId=doc_id,
        body={"requests": [{"updateDocumentStyle": {
            "documentStyle": {
                "marginTop": {"magnitude": 36, "unit": "PT"},
                "marginBottom": {"magnitude": 36, "unit": "PT"},
                "marginLeft": {"magnitude": 36, "unit": "PT"},
                "marginRight": {"magnitude": 36, "unit": "PT"},
            },
            "fields": "marginTop,marginBottom,marginLeft,marginRight",
        }}]},
    ).execute()

    # Parse and format
    if doc_type == "cover_letter":
        segments = parse_cover_letter(markdown)
        items = build_cover_letter_items(segments)
        requests = items_to_requests(items, default_size=11, default_spacing=115)
    else:
        segments = parse_resume(markdown)
        items = build_resume_items(segments)
        requests = items_to_requests(items)

    if requests:
        docs_service.documents().batchUpdate(
            documentId=doc_id,
            body={"requests": requests},
        ).execute()

    logger.info("Formatted %s document %s (%d requests)", doc_type, doc_id, len(requests))
