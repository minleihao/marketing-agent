from __future__ import annotations

import html
import re
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, StyleSheet1, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer


ROOT = Path(__file__).resolve().parent.parent
INPUT_MD = ROOT / "MARKETING_TEAM_USER_GUIDE.md"
OUTPUT_PDF = ROOT / "output" / "pdf" / "marketing-team-user-guide.pdf"


def build_styles() -> StyleSheet1:
    styles = getSampleStyleSheet()
    styles.add(
        ParagraphStyle(
            name="GuideTitle",
            parent=styles["Title"],
            fontName="Helvetica-Bold",
            fontSize=24,
            leading=28,
            textColor=colors.HexColor("#102037"),
            alignment=TA_CENTER,
            spaceAfter=12,
        )
    )
    styles.add(
        ParagraphStyle(
            name="GuideSubtitle",
            parent=styles["BodyText"],
            fontName="Helvetica",
            fontSize=11,
            leading=16,
            textColor=colors.HexColor("#4f647f"),
            alignment=TA_CENTER,
            spaceAfter=20,
        )
    )
    styles.add(
        ParagraphStyle(
            name="GuideH1",
            parent=styles["Heading1"],
            fontName="Helvetica-Bold",
            fontSize=17,
            leading=21,
            textColor=colors.HexColor("#0b6fde"),
            spaceBefore=12,
            spaceAfter=8,
        )
    )
    styles.add(
        ParagraphStyle(
            name="GuideH2",
            parent=styles["Heading2"],
            fontName="Helvetica-Bold",
            fontSize=13,
            leading=17,
            textColor=colors.HexColor("#173961"),
            spaceBefore=10,
            spaceAfter=6,
        )
    )
    styles.add(
        ParagraphStyle(
            name="GuideBody",
            parent=styles["BodyText"],
            fontName="Helvetica",
            fontSize=10.5,
            leading=15,
            textColor=colors.HexColor("#102037"),
            spaceAfter=6,
        )
    )
    styles.add(
        ParagraphStyle(
            name="GuideQuote",
            parent=styles["GuideBody"],
            leftIndent=18,
            rightIndent=10,
            borderPadding=10,
            backColor=colors.HexColor("#f3f8ff"),
            borderColor=colors.HexColor("#c9daf3"),
            borderWidth=0.75,
            borderLeft=True,
            textColor=colors.HexColor("#173961"),
            spaceBefore=4,
            spaceAfter=10,
        )
    )
    styles.add(
        ParagraphStyle(
            name="GuideList",
            parent=styles["GuideBody"],
            leftIndent=2,
            firstLineIndent=0,
            spaceAfter=2,
        )
    )
    return styles


def format_inline(text: str) -> str:
    escaped = html.escape(text.strip())
    escaped = re.sub(r"`([^`]+)`", r'<font name="Courier">\1</font>', escaped)
    return escaped


def add_footer(canvas, doc) -> None:
    canvas.saveState()
    width, _ = letter
    canvas.setStrokeColor(colors.HexColor("#d6dfec"))
    canvas.line(doc.leftMargin, 0.6 * inch, width - doc.rightMargin, 0.6 * inch)
    canvas.setFont("Helvetica", 9)
    canvas.setFillColor(colors.HexColor("#4f647f"))
    canvas.drawString(doc.leftMargin, 0.4 * inch, "Marketing Copilot User Guide")
    canvas.drawRightString(width - doc.rightMargin, 0.4 * inch, f"Page {doc.page}")
    canvas.restoreState()


def flush_paragraph(buffer: list[str], story: list, styles: StyleSheet1) -> None:
    if not buffer:
        return
    text = " ".join(part.strip() for part in buffer if part.strip())
    if text:
        story.append(Paragraph(format_inline(text), styles["GuideBody"]))
    buffer.clear()


def flush_list(items: list[tuple[str, bool]], story: list, styles: StyleSheet1) -> None:
    if not items:
        return
    if items[0][1]:
        for idx, (text, _) in enumerate(items, start=1):
            story.append(
                Paragraph(
                    format_inline(text),
                    styles["GuideList"],
                    bulletText=f"{idx}.",
                )
            )
    else:
        for text, _ in items:
            story.append(
                Paragraph(
                    format_inline(text),
                    styles["GuideList"],
                    bulletText="•",
                )
            )
    story.append(Spacer(1, 6))
    items.clear()


def build_story(markdown_text: str, styles: StyleSheet1) -> list:
    story: list = []
    lines = markdown_text.splitlines()
    paragraph_buffer: list[str] = []
    list_buffer: list[tuple[str, bool]] = []
    in_code_block = False

    story.append(Spacer(1, 0.45 * inch))
    story.append(Paragraph("Marketing Copilot User Guide", styles["GuideTitle"]))
    story.append(
        Paragraph(
            "Plain-language guide for marketers, content teams, and campaign managers",
            styles["GuideSubtitle"],
        )
    )
    story.append(Spacer(1, 0.1 * inch))

    for raw_line in lines:
        line = raw_line.rstrip()
        stripped = line.strip()

        if stripped.startswith("```"):
            in_code_block = not in_code_block
            continue
        if in_code_block:
            continue

        if not stripped:
            flush_paragraph(paragraph_buffer, story, styles)
            flush_list(list_buffer, story, styles)
            continue

        if stripped.startswith("# "):
            flush_paragraph(paragraph_buffer, story, styles)
            flush_list(list_buffer, story, styles)
            # Title handled separately.
            continue

        if stripped.startswith("## "):
            flush_paragraph(paragraph_buffer, story, styles)
            flush_list(list_buffer, story, styles)
            title = stripped[3:].strip()
            if title == "Quick Start":
                story.append(PageBreak())
            story.append(Paragraph(format_inline(title), styles["GuideH1"]))
            continue

        if stripped.startswith("### "):
            flush_paragraph(paragraph_buffer, story, styles)
            flush_list(list_buffer, story, styles)
            story.append(Paragraph(format_inline(stripped[4:].strip()), styles["GuideH2"]))
            continue

        if stripped.startswith("> "):
            flush_paragraph(paragraph_buffer, story, styles)
            flush_list(list_buffer, story, styles)
            story.append(Paragraph(format_inline(stripped[2:]), styles["GuideQuote"]))
            continue

        unordered_match = re.match(r"^- (.+)", stripped)
        ordered_match = re.match(r"^\d+\. (.+)", stripped)
        if unordered_match:
            flush_paragraph(paragraph_buffer, story, styles)
            list_buffer.append((unordered_match.group(1), False))
            continue
        if ordered_match:
            flush_paragraph(paragraph_buffer, story, styles)
            list_buffer.append((ordered_match.group(1), True))
            continue

        flush_list(list_buffer, story, styles)
        paragraph_buffer.append(stripped)

    flush_paragraph(paragraph_buffer, story, styles)
    flush_list(list_buffer, story, styles)
    return story


def main() -> None:
    OUTPUT_PDF.parent.mkdir(parents=True, exist_ok=True)
    markdown_text = INPUT_MD.read_text(encoding="utf-8")
    styles = build_styles()
    story = build_story(markdown_text, styles)
    doc = SimpleDocTemplate(
        str(OUTPUT_PDF),
        pagesize=letter,
        leftMargin=0.75 * inch,
        rightMargin=0.75 * inch,
        topMargin=0.75 * inch,
        bottomMargin=0.9 * inch,
        title="Marketing Copilot User Guide",
        author="OpenAI Codex",
    )
    doc.build(story, onFirstPage=add_footer, onLaterPages=add_footer)
    print(OUTPUT_PDF)


if __name__ == "__main__":
    main()
