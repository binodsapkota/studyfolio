from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

STUDY_NOTE = (
    "Studyfolio study draft. Review and edit before submitting. "
    "Dosage results are for practice problems, not for giving a medication "
    "or writing a real chart."
)

Intent = Literal["chat", "explain", "math", "write", "grammar", "table", "export", "clarify"]


class Understanding(BaseModel):
    intent: Intent
    request: str = ""
    confidence: float = 0.8
    question: str = ""
    options: list[str] = Field(default_factory=list)


class MathSolution(BaseModel):
    problem: str
    approach: Literal["sympy", "dosage"] = "sympy"
    steps: list[str] = Field(default_factory=list)
    expressions: list[str] = Field(default_factory=list)
    formula: Literal[
        "none",
        "tablets",
        "weight_based",
        "iv_rate",
        "drip_rate",
        "reconstitution",
    ] = "none"
    desired_dose: float | None = None
    desired_unit: str = ""
    have_dose: float | None = None
    have_unit: str = ""
    weight: float | None = None
    weight_unit: str = ""
    dose_per_kg: float | None = None
    dose_per_kg_unit: str = ""
    volume_ml: float | None = None
    volume_unit: str = "mL"
    hours: float | None = None
    minutes: float | None = None
    drop_factor: float | None = None
    concentration: float | None = None
    concentration_unit: str = ""
    unsure_notes: str = ""


class Section(BaseModel):
    heading: str
    paragraphs: list[str] = Field(default_factory=list)
    bullets: list[str] = Field(default_factory=list)


class StudyDocument(BaseModel):
    title: str
    kind: Literal[
        "essay",
        "outline",
        "care_plan",
        "concept_map",
        "teaching_plan",
        "sbar",
        "reflection",
        "solution",
        "grammar",
    ] = "essay"
    author_note: str = STUDY_NOTE
    sections: list[Section] = Field(default_factory=list)
    references: list[str] = Field(default_factory=list)
    show_title: bool = True


class SheetModel(BaseModel):
    name: str = "Sheet1"
    headers: list[str] = Field(default_factory=list)
    rows: list[list[str]] = Field(default_factory=list)


class WorkbookModel(BaseModel):
    title: str
    sheets: list[SheetModel] = Field(default_factory=list)


class VisionReading(BaseModel):
    question_text: str
    equations: list[str] = Field(default_factory=list)
    diagram_notes: str = ""
    uncertain_bits: list[str] = Field(default_factory=list)

    def as_text(self) -> str:
        def real(text: str) -> bool:
            return text.strip().lower().strip(".") not in ("", "none", "n/a", "na", "null")

        lines = [self.question_text.strip()]
        equations = [item for item in self.equations if real(item) and item.strip() not in self.question_text]
        if equations:
            lines.append("Equations: " + "; ".join(equations))
        if real(self.diagram_notes):
            lines.append("Visual details: " + self.diagram_notes.strip())
        unclear = [item for item in self.uncertain_bits if real(item)]
        if unclear:
            lines.append("Unclear: " + "; ".join(unclear))
        return "\n".join(line for line in lines if line)
