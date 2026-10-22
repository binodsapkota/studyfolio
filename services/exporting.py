from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from agent.format import document_from_markdown, markdown_title, workbook_from_markdown
from agent.intent import FORMAT_LABELS
from exporters.docx_export import docx_bytes
from exporters.pdf_export import pdf_bytes
from exporters.xlsx_export import xlsx_bytes
from services.paths import OUTPUTS
MIME_TYPES = {
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "pdf": "application/pdf",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}


def stem(title: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9]+", "-", title).strip("-").lower()
    return (cleaned or "studyfolio")[:40]


def strip_lead_in(markdown: str, limit: int = 300) -> str:
    """Drop chatty text such as "Here's a revised version:" that comes before the document title."""
    match = re.search(r"^\s*# \S", markdown, flags=re.MULTILINE)
    if match and 0 < len(markdown[: match.start()].strip()) <= limit:
        return markdown[match.start() :].lstrip()
    return markdown


def export_markdown(
    markdown: str,
    formats: list[str],
    *,
    title_hint: str = "",
    folder: Path | None = None,
) -> tuple[list[dict], list[str]]:
    """Write the requested files. Returns the file records and the formats that could not be made."""
    markdown = strip_lead_in(markdown)
    title = markdown_title(markdown) or title_hint.strip() or "Studyfolio export"
    folder = folder or OUTPUTS
    folder.mkdir(parents=True, exist_ok=True)
    name = stem(title)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    records: list[dict] = []
    skipped: list[str] = []
    for fmt in formats:
        if fmt == "xlsx":
            workbook = workbook_from_markdown(markdown, title)
            if workbook is None:
                skipped.append(fmt)
                continue
            data = xlsx_bytes(workbook)
        elif fmt in ("docx", "pdf"):
            document = document_from_markdown(markdown, title)
            data = docx_bytes(document) if fmt == "docx" else pdf_bytes(document)
        else:
            skipped.append(fmt)
            continue
        path = folder / f"{stamp}-{name}.{fmt}"
        path.write_bytes(data)
        records.append(
            {
                "format": fmt,
                "label": FORMAT_LABELS[fmt],
                "path": str(path),
                "file_name": f"{name}.{fmt}",
                "mime": MIME_TYPES[fmt],
            }
        )
    return records, skipped
