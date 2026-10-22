from __future__ import annotations

import re

from agent.schema import STUDY_NOTE, Section, SheetModel, StudyDocument, WorkbookModel

_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")
_BULLET = re.compile(r"^[-*+•]\s+(.*)$")
_NUMBERED = re.compile(r"^(\d+[.)])\s+(.*)$")
_TABLE_SEPARATOR = re.compile(r"^\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?$")


def document_to_markdown(document: StudyDocument) -> str:
    lines = [f"# {document.title}", "", f"_{document.author_note or STUDY_NOTE}_", ""]
    for section in document.sections:
        lines.append(f"## {section.heading}")
        lines.append("")
        for paragraph in section.paragraphs:
            lines.append(paragraph)
            lines.append("")
        for bullet in section.bullets:
            lines.append(f"- {bullet}")
        if section.bullets:
            lines.append("")
    if document.references:
        lines.append("## References")
        lines.append("")
        for reference in document.references:
            lines.append(f"- {reference}")
    return "\n".join(lines).strip() + "\n"


def with_line_breaks(markdown: str) -> str:
    """Render single newlines as line breaks, the way chat apps show letters and poems."""
    lines = markdown.split("\n")
    in_code = False
    for index, line in enumerate(lines[:-1]):
        if line.strip().startswith("```"):
            in_code = not in_code
            continue
        following = lines[index + 1].strip()
        if in_code or not line.strip() or not following or "|" in (line.lstrip()[:1], following[:1]):
            continue
        if not line.endswith("  ") and not line.endswith("\\"):
            lines[index] = line.rstrip() + "  "
    return "\n".join(lines)


def clean_inline(text: str) -> str:
    text = re.sub(r"!\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"\1 (\2)", text)
    text = re.sub(r"(\*\*|__)(.+?)\1", r"\2", text)
    text = re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])", r"\1", text)
    text = re.sub(r"(?<![\w_])_(?!\s)(.+?)(?<!\s)_(?![\w_])", r"\1", text)
    text = re.sub(r"`([^`]+)`", r"\1", text)
    return text.strip()


def markdown_title(markdown: str) -> str:
    for line in markdown.splitlines():
        match = _HEADING.match(line.strip())
        if match:
            return clean_inline(match.group(2))
    return ""


def _table_cells(line: str) -> list[str]:
    body = line.strip()
    if body.startswith("|"):
        body = body[1:]
    if body.endswith("|"):
        body = body[:-1]
    return [clean_inline(cell.replace("\\|", "|")) for cell in body.split("|")]


def document_from_markdown(markdown: str, title: str = "") -> StudyDocument:
    """Untitled content (letters, emails, poems) is exported as written, without a title or study note."""
    titled = bool(re.search(r"^\s*# \S", markdown, flags=re.MULTILINE))
    title = title.strip() or markdown_title(markdown) or "Studyfolio answer"
    sections: list[Section] = []
    paragraph: list[str] = []
    skipped_title = False
    in_code = False

    def target(for_paragraph: bool) -> Section:
        # Sections print paragraphs before bullets, so text after a list starts a new block.
        if not sections or (for_paragraph and sections[-1].bullets):
            sections.append(Section(heading=""))
        return sections[-1]

    def flush() -> None:
        if paragraph:
            # Keep the author's line breaks: address blocks, letters, and poems depend on them.
            target(True).paragraphs.append("\n".join(paragraph))
            paragraph.clear()

    for raw in markdown.splitlines():
        line = raw.strip()
        if line.startswith("```"):
            flush()
            in_code = not in_code
            continue
        if in_code:
            if line:
                target(True).paragraphs.append(raw.rstrip())
            continue
        if not line or re.fullmatch(r"[-*_]{3,}", line):
            flush()
            continue
        heading = _HEADING.match(line)
        if heading:
            flush()
            text = clean_inline(heading.group(2))
            if not skipped_title and not sections and text == title:
                skipped_title = True
                continue
            sections.append(Section(heading=text))
            continue
        if line.startswith("|"):
            flush()
            if not _TABLE_SEPARATOR.match(line):
                target(False).bullets.append(" | ".join(_table_cells(line)))
            continue
        bullet = _BULLET.match(line)
        if bullet:
            flush()
            target(False).bullets.append(clean_inline(bullet.group(1)))
            continue
        numbered = _NUMBERED.match(line)
        if numbered:
            flush()
            target(True).paragraphs.append(f"{numbered.group(1)} {clean_inline(numbered.group(2))}")
            continue
        paragraph.append(clean_inline(line.rstrip("\\")))
    flush()
    sections = [item for item in sections if item.heading or item.paragraphs or item.bullets]
    if not sections:
        sections = [Section(heading="", paragraphs=["No answer text was saved."])]
    return StudyDocument(
        title=title,
        kind="solution",
        sections=sections,
        show_title=titled,
        author_note=STUDY_NOTE if titled else "",
    )


def workbook_from_markdown(markdown: str, title: str = "") -> WorkbookModel | None:
    title = title.strip() or markdown_title(markdown) or "Studyfolio table"
    sheets: list[SheetModel] = []
    last_heading = ""
    rows: list[list[str]] = []

    def close() -> None:
        if rows:
            headers, body = rows[0], rows[1:]
            name = last_heading or f"Table {len(sheets) + 1}"
            sheets.append(SheetModel(name=name, headers=headers, rows=body))
            rows.clear()

    for raw in markdown.splitlines():
        line = raw.strip()
        if line.startswith("|"):
            if not _TABLE_SEPARATOR.match(line):
                rows.append(_table_cells(line))
            continue
        close()
        heading = _HEADING.match(line)
        if heading:
            last_heading = clean_inline(heading.group(2))
    close()
    if not sheets:
        return None
    return WorkbookModel(title=title, sheets=sheets)
