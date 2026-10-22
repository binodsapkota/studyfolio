from __future__ import annotations

import os
from pathlib import Path

from fpdf import FPDF
from fpdf.enums import XPos, YPos

from agent.schema import StudyDocument


def pdf_bytes(document: StudyDocument) -> bytes:
    regular, bold = _font_paths()
    pdf = FPDF(format="Letter")
    pdf.set_auto_page_break(auto=True, margin=18)
    pdf.add_page()
    pdf.add_font("Body", "", str(regular))
    pdf.add_font("Body", "B", str(bold))
    if document.show_title:
        _write(pdf, document.title, 9, bold=True, size=18)
        pdf.ln(2)
    if document.author_note.strip():
        _write(pdf, document.author_note, 6, size=11)
        pdf.ln(3)
    for section in document.sections:
        if section.heading.strip():
            _write(pdf, section.heading, 8, bold=True, size=14)
        for paragraph in section.paragraphs:
            _write(pdf, paragraph, 6, size=12)
            pdf.ln(1)
        for bullet in section.bullets:
            _write(pdf, f"- {bullet}", 6, size=12)
        pdf.ln(2)
    if document.references:
        _write(pdf, "References", 8, bold=True, size=14)
        for reference in document.references:
            _write(pdf, reference, 6, size=12)
            pdf.ln(1)
    return bytes(pdf.output())


def _write(pdf: FPDF, text: str, height: float, *, bold: bool = False, size: int = 12) -> None:
    pdf.set_font("Body", "B" if bold else "", size)
    pdf.set_x(pdf.l_margin)
    pdf.multi_cell(0, height, text, new_x=XPos.LMARGIN, new_y=YPos.NEXT)


def write_pdf(document: StudyDocument, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(pdf_bytes(document))
    return path


def _font_paths() -> tuple[Path, Path]:
    fonts = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
    regular = fonts / "calibri.ttf"
    bold = fonts / "calibrib.ttf"
    if not regular.exists():
        regular = fonts / "arial.ttf"
        bold = fonts / "arialbd.ttf"
    if not regular.exists():
        raise FileNotFoundError("Calibri or Arial is required to export a PDF.")
    if not bold.exists():
        bold = regular
    return regular, bold
