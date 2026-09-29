"""Renders the Markdown a user edited in the tailored-resume editor into a
print-ready PDF with ReportLab.

This is a deliberately small Markdown subset — headings, bullets, bold /
italic / code / links, horizontal rules — i.e. exactly what
`templates/resume_template.md` and the generator produce, plus the usual
things someone hand-edits into a resume. Anything unrecognized falls
through as plain text instead of raising.
"""

import io
import logging
import re
from xml.sax.saxutils import escape

from django.conf import settings
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4, LETTER
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import HRFlowable, Paragraph, SimpleDocTemplate, Spacer

logger = logging.getLogger(__name__)

HEADING_RE = re.compile(r"^(#{1,6})\s*(.*)$")
BULLET_RE = re.compile(r"^[-*+]\s+(.*)$")
ORDERED_RE = re.compile(r"^(\d+)[.)]\s+(.*)$")
QUOTE_RE = re.compile(r"^>\s?(.*)$")
RULE_RE = re.compile(r"^(?:-{3,}|\*{3,}|_{3,})$")
SURROUNDING_STARS_RE = re.compile(r"^\*+(.*?)\*+$")

PAGE_SIZES = {"letter": LETTER, "a4": A4}

INK = colors.HexColor("#111827")
MUTED = colors.HexColor("#4b5563")
RULE = colors.HexColor("#9ca3af")
LINK_HEX = "#08786a"


def _styles() -> dict[str, ParagraphStyle]:
    base = ParagraphStyle(
        "body",
        fontName="Helvetica",
        fontSize=9.8,
        leading=13.2,
        textColor=INK,
        spaceAfter=5,
    )
    return {
        "body": base,
        "name": ParagraphStyle(
            "name",
            parent=base,
            fontName="Helvetica-Bold",
            fontSize=19,
            leading=23,
            alignment=TA_CENTER,
            spaceAfter=3,
        ),
        "contact": ParagraphStyle(
            "contact",
            parent=base,
            fontSize=9,
            leading=12.5,
            textColor=MUTED,
            alignment=TA_CENTER,
            spaceAfter=2,
        ),
        "section": ParagraphStyle(
            "section",
            parent=base,
            fontName="Helvetica-Bold",
            fontSize=11,
            leading=14,
            textColor=INK,
            spaceBefore=10,
            spaceAfter=2,
        ),
        "subheading": ParagraphStyle(
            "subheading",
            parent=base,
            fontName="Helvetica-Bold",
            fontSize=10.5,
            leading=13.5,
            spaceBefore=7,
            spaceAfter=1,
        ),
        "meta": ParagraphStyle(
            "meta", parent=base, fontName="Helvetica-Oblique", textColor=MUTED, spaceAfter=3
        ),
        "bullet": ParagraphStyle(
            "bullet", parent=base, leftIndent=13, bulletIndent=2, spaceAfter=2.5
        ),
        "quote": ParagraphStyle(
            "quote",
            parent=base,
            fontName="Helvetica-Oblique",
            leftIndent=13,
            textColor=MUTED,
        ),
    }


def _inline(text: str) -> str:
    """Convert inline Markdown to the mini-HTML ReportLab paragraphs speak."""

    text = escape(text)
    text = re.sub(r"!\[([^\]]*)\]\([^)]*\)", r"\1", text)  # images -> their alt text
    text = re.sub(
        r"\[([^\]]+)\]\(([^)\s]+)\)", rf'<link href="\2" color="{LINK_HEX}">\1</link>', text
    )
    text = re.sub(r"`([^`]+)`", r'<font face="Courier">\1</font>', text)
    text = re.sub(r"\*\*(\S.*?)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"__(\S.*?)__", r"<b>\1</b>", text)
    text = re.sub(r"(?<![\w*])\*(\S.*?)\*(?!\w)", r"<i>\1</i>", text)
    text = re.sub(r"(?<![\w_])_(\S.*?)_(?!\w)", r"<i>\1</i>", text)
    return text


def _heading_text(text: str) -> str:
    """`## **SKILLS**` and `## SKILLS` should both read as "SKILLS" — the
    heading style is already bold."""

    match = SURROUNDING_STARS_RE.match(text.strip())
    return match.group(1).strip() if match else text.strip()


def _paragraph(markup: str, style, *, plain: str = "", **kwargs) -> Paragraph:
    """Build a paragraph, falling back to plain text when the converted
    markup comes out unbalanced (e.g. `*one **two* three**` in a
    hand-edited resume) — an odd line must not fail the whole export."""

    try:
        return Paragraph(markup, style, **kwargs)
    except Exception:
        logger.warning("Falling back to plain text for an unparsable resume line.")
        safe = escape(plain or markup).replace("\n", "<br/>")
        return Paragraph(safe, style, **kwargs)


def markdown_to_flowables(markdown_text: str, styles=None) -> list:
    """Turn Markdown into a ReportLab story.

    Everything above the first `#`/`##` heading is treated as the resume
    header (name + contact details) and centered, matching the layout of
    `templates/resume_template.md`. Consecutive plain lines are kept as
    separate lines rather than reflowed into one paragraph, so what the
    user typed in the editor is what they get on the page.
    """

    styles = styles or _styles()
    story: list = []
    paragraph: list[tuple[str, str]] = []
    in_header = True
    header_done = False

    def flush():
        nonlocal paragraph, header_done
        if not paragraph:
            return
        markup = "<br/>".join(markup_line for markup_line, _ in paragraph)
        plain = "\n".join(raw_line for _, raw_line in paragraph)
        paragraph = []
        if in_header and not header_done:
            header_done = True
            style = styles["name"]
        elif in_header:
            style = styles["contact"]
        else:
            style = styles["body"]
        story.append(_paragraph(markup, style, plain=plain))

    for raw_line in markdown_text.replace("\r\n", "\n").split("\n"):
        line = raw_line.strip()

        if not line:
            flush()
            continue

        if RULE_RE.match(line):
            flush()
            story.append(Spacer(1, 3))
            story.append(HRFlowable(width="100%", thickness=0.6, color=RULE, spaceAfter=6))
            continue

        heading = HEADING_RE.match(line)
        if heading:
            flush()
            level = len(heading.group(1))
            text = _heading_text(heading.group(2))
            if level <= 2:
                in_header = False
            if not text:
                continue
            if level == 1:
                story.append(_paragraph(_inline(text), styles["name"], plain=text))
            elif level == 2:
                story.append(
                    _paragraph(_inline(text.upper()), styles["section"], plain=text.upper())
                )
                story.append(
                    HRFlowable(width="100%", thickness=0.6, color=RULE, spaceBefore=1, spaceAfter=5)
                )
            else:
                story.append(_paragraph(_inline(text), styles["subheading"], plain=text))
            continue

        bullet = BULLET_RE.match(line)
        if bullet:
            flush()
            story.append(
                _paragraph(
                    _inline(bullet.group(1)),
                    styles["bullet"],
                    plain=bullet.group(1),
                    bulletText="•",
                )
            )
            continue

        ordered = ORDERED_RE.match(line)
        if ordered:
            flush()
            story.append(
                _paragraph(
                    _inline(ordered.group(2)),
                    styles["bullet"],
                    plain=ordered.group(2),
                    bulletText=f"{ordered.group(1)}.",
                )
            )
            continue

        quote = QUOTE_RE.match(line)
        if quote:
            flush()
            story.append(_paragraph(_inline(quote.group(1)), styles["quote"], plain=quote.group(1)))
            continue

        # A line of italics on its own (dates, location) is the meta line
        # under a role or degree heading.
        is_meta_line = line.startswith("*") and line.endswith("*") and not line.startswith("**")
        if not in_header and is_meta_line:
            flush()
            story.append(_paragraph(_inline(line), styles["meta"], plain=line))
            continue

        paragraph.append((_inline(line), line))

    flush()
    return story


def render_markdown_pdf(markdown_text: str, *, title: str = "Resume", author: str = "") -> bytes:
    """Render Markdown to PDF bytes, ready to serve as a download."""

    page_size = PAGE_SIZES.get(str(settings.RESUME_PDF_PAGE_SIZE).lower(), LETTER)
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=page_size,
        leftMargin=0.7 * inch,
        rightMargin=0.7 * inch,
        topMargin=0.6 * inch,
        bottomMargin=0.6 * inch,
        title=title,
        author=author,
    )
    story = markdown_to_flowables(markdown_text)
    if not story:
        story = [Paragraph("", _styles()["body"])]
    doc.build(story)
    return buffer.getvalue()
