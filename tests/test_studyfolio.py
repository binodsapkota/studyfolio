import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent.format import document_from_markdown, document_to_markdown, with_line_breaks, workbook_from_markdown
from agent.graph import math_node, plan_turn
from agent.intent import (
    export_formats,
    export_requested,
    fix_typos,
    is_export_command,
    mentions_export,
    missing_topic,
    requested_words,
    topic_question,
    writing_kind,
)
from agent.schema import (
    MathSolution,
    Section,
    SheetModel,
    StudyDocument,
    Understanding,
    VisionReading,
    WorkbookModel,
)
from exporters.docx_export import docx_bytes
from exporters.pdf_export import pdf_bytes
from exporters.xlsx_export import xlsx_bytes
from services.dosage import DosageError, compute_dosage
from services.exporting import strip_lead_in
from services.math_solver import MathCheckError, evaluate_expression
from services.ollama_client import parse_model_json


class DosageTests(unittest.TestCase):
    def test_tablets_convert_micrograms(self) -> None:
        result = compute_dosage(
            "tablets",
            desired_dose=1000,
            desired_unit="mcg",
            have_dose=1,
            have_unit="mg",
        )
        self.assertAlmostEqual(result.value, 1)

    def test_weight_based_pounds(self) -> None:
        result = compute_dosage(
            "weight_based",
            weight=154,
            weight_unit="lb",
            dose_per_kg=5,
            dose_per_kg_unit="mg",
        )
        self.assertAlmostEqual(result.value, 154 * 0.45359237 * 5, places=4)

    def test_iv_rate(self) -> None:
        result = compute_dosage("iv_rate", volume_ml=1, volume_unit="L", hours=8)
        self.assertAlmostEqual(result.value, 125)

    def test_drip_rate(self) -> None:
        result = compute_dosage(
            "drip_rate",
            volume_ml=1000,
            drop_factor=15,
            hours=8,
        )
        self.assertAlmostEqual(result.value, 31.25)

    def test_reconstitution(self) -> None:
        result = compute_dosage(
            "reconstitution",
            desired_dose=500,
            desired_unit="mg",
            concentration=250,
            concentration_unit="mg/mL",
        )
        self.assertAlmostEqual(result.value, 2)

    def test_missing_dose_is_rejected(self) -> None:
        with self.assertRaises(DosageError):
            compute_dosage("tablets", have_dose=250, have_unit="mg")

    def test_unknown_unit_is_rejected(self) -> None:
        with self.assertRaises(DosageError):
            compute_dosage(
                "weight_based",
                weight=10,
                weight_unit="stone",
                dose_per_kg=5,
                dose_per_kg_unit="mg",
            )


class MathTests(unittest.TestCase):
    def test_derivative(self) -> None:
        self.assertEqual(evaluate_expression("diff(x**2, x)"), "2*x")

    def test_solve(self) -> None:
        self.assertEqual(evaluate_expression("solve(x**2 - 4, x)"), "[-2, 2]")

    def test_rejects_python_calls(self) -> None:
        with self.assertRaises(MathCheckError):
            evaluate_expression("__import__('os')")


class ExportTests(unittest.TestCase):
    def test_document_exports(self) -> None:
        document = StudyDocument(
            title="Fluid balance",
            kind="care_plan",
            sections=[
                Section(
                    heading="Nursing diagnosis",
                    paragraphs=["Risk for deficient fluid volume."],
                    bullets=["Monitor intake and output."],
                )
            ],
            references=["[citation needed]"],
        )
        self.assertIn("Fluid balance", document_to_markdown(document))
        self.assertTrue(docx_bytes(document).startswith(b"PK"))
        self.assertTrue(pdf_bytes(document).startswith(b"%PDF"))

    def test_workbook_export_keeps_formulas(self) -> None:
        workbook = WorkbookModel(
            title="Intake",
            sheets=[
                SheetModel(
                    name="Day 1",
                    headers=["Item", "mL"],
                    rows=[["Oral", "240"], ["IV", "500"], ["Total", "=B2+B3"]],
                )
            ],
        )
        payload = xlsx_bytes(workbook)
        self.assertTrue(payload.startswith(b"PK"))


class IntentTests(unittest.TestCase):
    def test_export_commands(self) -> None:
        self.assertTrue(is_export_command("export it as pdf"))
        self.assertTrue(is_export_command("Can you download this as a Word doc?"))
        self.assertTrue(is_export_command("export"))
        self.assertTrue(is_export_command("please convert to excel"))
        self.assertFalse(is_export_command("How do I export a chart in Excel?"))
        self.assertFalse(is_export_command("Make an Excel intake sheet"))
        self.assertFalse(is_export_command("Write a 500 word essay on asthma"))

    def test_formats(self) -> None:
        self.assertEqual(export_formats("save it as a word doc"), ["docx"])
        self.assertEqual(export_formats("PDF"), ["pdf"])
        self.assertEqual(export_formats("both"), ["docx", "pdf"])
        self.assertEqual(export_formats("Yes, as Word"), ["docx"])
        self.assertEqual(export_formats("Write a 500 word essay"), [])
        self.assertEqual(export_formats("export to excel and pdf"), ["pdf", "xlsx"])

    def test_mentions_export(self) -> None:
        self.assertTrue(mentions_export("Write an essay on asthma and export it as pdf"))
        self.assertFalse(mentions_export("Write an essay on asthma"))

    def test_export_requested_in_a_clause(self) -> None:
        self.assertTrue(export_requested("Write an essay on asthma and export it as pdf"))
        self.assertTrue(export_requested("Looks good, now download it as a Word doc"))
        self.assertFalse(export_requested("How do I export a chart in Excel?"))

    def test_missing_topic(self) -> None:
        self.assertTrue(missing_topic("write an essay"))
        self.assertTrue(missing_topic("Can you write me a care plan?"))
        self.assertFalse(missing_topic("write an essay on asthma triggers"))

    def test_writing_kind(self) -> None:
        self.assertEqual(writing_kind("Write a leave letter to my principal"), "letter")
        self.assertEqual(writing_kind("write a cover letter for a nursing job"), "cover_letter")
        self.assertEqual(writing_kind("Draft an email to my professor about the deadline"), "email")
        self.assertEqual(writing_kind("a poem about the ocean"), "poem")
        self.assertEqual(writing_kind("500-word essay on climate change"), "essay")
        self.assertEqual(writing_kind("make it more formal", "Rewrite the complaint letter"), "letter")
        self.assertEqual(writing_kind("hello"), "general")

    def test_writing_typos(self) -> None:
        self.assertEqual(fix_typos("write easy on blood pressure"), "write essay on blood pressure")
        self.assertEqual(fix_typos("write an essey about asthma"), "write an essay about asthma")
        self.assertEqual(fix_typos("write a 300 word easy on diabetes"), "write a 300 word essay on diabetes")
        self.assertEqual(fix_typos("write a latter to my principal"), "write a letter to my principal")
        self.assertEqual(fix_typos("give an easy explanation of shock"), "give an easy explanation of shock")
        self.assertEqual(fix_typos("make it easy to read"), "make it easy to read")
        self.assertEqual(fix_typos("the latter option is better"), "the latter option is better")
        self.assertEqual(writing_kind("write easy on blood pressure"), "essay")
        self.assertTrue(missing_topic("write an easy"))

    def test_requested_words(self) -> None:
        self.assertEqual(requested_words("Write a 500-word essay"), 500)
        self.assertEqual(requested_words("between 300 to 450 words please"), 450)
        self.assertEqual(requested_words("1,200 words on asthma"), 1200)
        self.assertEqual(requested_words("two pages on asthma"), 600)
        self.assertEqual(requested_words("in 3 short paragraphs"), 360)
        self.assertIsNone(requested_words("Write an essay on asthma"))
        self.assertIsNone(requested_words("1000 mL over 8 hours"))

    def test_topic_questions_match_the_kind(self) -> None:
        self.assertTrue(missing_topic("write a formal letter"))
        self.assertFalse(missing_topic("write a letter to my landlord about the leak"))
        self.assertIn("Who is the letter to", topic_question("write a letter", "write"))
        self.assertIn("email", topic_question("write an email", "write"))
        self.assertIn("essay", topic_question("write an essay", "write"))

    def test_understanding_parses_from_fence(self) -> None:
        raw = '```json\n{"intent": "explain", "request": "Explain ABCs", "confidence": 0.9}\n```'
        decision = parse_model_json(raw, Understanding)
        self.assertEqual(decision.intent, "explain")


class MarkdownTests(unittest.TestCase):
    SAMPLE = (
        "# Asthma care plan\n\n"
        "Intro paragraph with **bold** text.\n\n"
        "## Interventions\n\n"
        "- Monitor SpO2\n"
        "- Teach inhaler use\n\n"
        "Closing line.\n\n"
        "## Intake\n\n"
        "| Item | mL |\n|---|---|\n| Oral | 240 |\n| IV | 500 |\n"
    )

    def test_document_from_markdown(self) -> None:
        document = document_from_markdown(self.SAMPLE)
        self.assertEqual(document.title, "Asthma care plan")
        self.assertEqual(document.sections[0].paragraphs, ["Intro paragraph with bold text."])
        interventions = document.sections[1]
        self.assertEqual(interventions.heading, "Interventions")
        self.assertEqual(interventions.bullets, ["Monitor SpO2", "Teach inhaler use"])
        self.assertEqual(document.sections[2].paragraphs, ["Closing line."])
        self.assertTrue(docx_bytes(document).startswith(b"PK"))
        self.assertTrue(pdf_bytes(document).startswith(b"%PDF"))

    def test_letter_keeps_lines_and_skips_title(self) -> None:
        letter = "[Your Name]\n[Address]\n[Date]\n\nDear Ms. Rao,\n\nI am writing to request leave.\n\nSincerely,\n[Your Name]"
        document = document_from_markdown(letter, "Leave letter")
        self.assertFalse(document.show_title)
        self.assertEqual(document.author_note, "")
        self.assertEqual(document.sections[0].paragraphs[0], "[Your Name]\n[Address]\n[Date]")
        self.assertTrue(docx_bytes(document).startswith(b"PK"))
        self.assertTrue(pdf_bytes(document).startswith(b"%PDF"))

    def test_line_breaks_for_chat(self) -> None:
        rendered = with_line_breaks("Dear Sam,\nThanks.\n\n| a | b |\n|---|---|\n| 1 | 2 |")
        self.assertIn("Dear Sam,  \nThanks.", rendered)
        self.assertIn("| a | b |\n|---|---|", rendered)

    def test_export_drops_lead_in(self) -> None:
        text = "Here's a revised version:\n\n# Asthma\n\nBody text."
        self.assertTrue(strip_lead_in(text).startswith("# Asthma"))
        self.assertEqual(strip_lead_in("No heading at all."), "No heading at all.")

    def test_workbook_from_markdown(self) -> None:
        workbook = workbook_from_markdown(self.SAMPLE)
        self.assertIsNotNone(workbook)
        sheet = workbook.sheets[0]
        self.assertEqual(sheet.name, "Intake")
        self.assertEqual(sheet.headers, ["Item", "mL"])
        self.assertEqual(sheet.rows, [["Oral", "240"], ["IV", "500"]])
        self.assertIsNone(workbook_from_markdown("No table here."))


class GraphTests(unittest.TestCase):
    """Paths that are decided without calling a model."""

    HISTORY = [
        {"id": "u1", "role": "user", "content": "Write a care plan for asthma"},
        {"id": "a1", "role": "assistant", "kind": "answer", "content": "# Asthma plan\n\n- Monitor SpO2"},
    ]

    def test_export_without_format_asks(self) -> None:
        plan = plan_turn("export it", history=self.HISTORY)
        self.assertEqual(plan.kind, "question")
        self.assertEqual(plan.pending, {"type": "export_format", "target": "a1"})
        self.assertEqual(plan.exports, [])

    def test_format_answer_exports(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            with mock.patch("services.exporting.OUTPUTS", Path(folder)):
                plan = plan_turn(
                    "PDF",
                    history=self.HISTORY,
                    pending={"type": "export_format", "target": "a1"},
                )
                self.assertEqual(plan.kind, "export")
                self.assertEqual([item["format"] for item in plan.exports], ["pdf"])
                self.assertTrue(Path(plan.exports[0]["path"]).exists())
                self.assertEqual(plan.exports[0]["file_name"], "asthma-plan.pdf")

    def test_untitled_answer_is_named_after_the_question(self) -> None:
        history = [
            {"id": "u1", "role": "user", "content": "What are the ABCs in nursing?"},
            {"id": "a1", "role": "assistant", "kind": "answer", "content": "Airway, breathing, circulation."},
        ]
        with tempfile.TemporaryDirectory() as folder:
            with mock.patch("services.exporting.OUTPUTS", Path(folder)):
                plan = plan_turn("export as word", history=history)
        self.assertEqual(plan.exports[0]["file_name"], "what-are-the-abcs-in-nursing.docx")

    def test_excel_without_table_asks(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            with mock.patch("services.exporting.OUTPUTS", Path(folder)):
                plan = plan_turn("export to excel", history=self.HISTORY)
        self.assertEqual(plan.kind, "question")
        self.assertIn("Word", plan.options)

    def test_nothing_to_export(self) -> None:
        plan = plan_turn("download as pdf", history=[])
        self.assertEqual(plan.kind, "question")
        self.assertEqual(plan.exports, [])

    def test_small_talk_streams_without_router(self) -> None:
        plan = plan_turn("thanks", history=self.HISTORY)
        self.assertEqual(plan.intent, "chat")
        self.assertTrue(plan.needs_stream)
        self.assertEqual(plan.turns[-1], ("user", "thanks"))
        self.assertEqual(plan.turns[0][0], "user")

    def test_model_export_guess_needs_confirmation(self) -> None:
        guess = Understanding(intent="export", request="Export the plan", confidence=0.9)
        with mock.patch("agent.graph.complete_schema", return_value=guess):
            plan = plan_turn("that looks great", history=self.HISTORY)
        self.assertEqual(plan.kind, "question")
        self.assertEqual(plan.pending["type"], "confirm_export")
        self.assertEqual(plan.exports, [])

    def test_low_confidence_asks(self) -> None:
        guess = Understanding(
            intent="write",
            request="?",
            confidence=0.2,
            question="Which topic should the essay cover?",
            options=["Asthma", "COPD"],
        )
        with mock.patch("agent.graph.complete_schema", return_value=guess):
            plan = plan_turn("do the essay", history=[])
        self.assertEqual(plan.intent, "clarify")
        self.assertEqual(plan.reply, "Which topic should the essay cover?")
        self.assertEqual(plan.options, ["Asthma", "COPD"])

    def test_missing_topic_asks(self) -> None:
        guess = Understanding(intent="write", request="Write an essay", confidence=0.9)
        with mock.patch("agent.graph.complete_schema", return_value=guess):
            plan = plan_turn("write an essay", history=[])
        self.assertEqual(plan.intent, "clarify")
        self.assertIn("essay", plan.reply)

    def test_iv_rate_fields_filled_from_request(self) -> None:
        state = {
            "intent": "math",
            "request": "Calculate mL/hr for 1,000 mL over 12 hours",
            "message": "what about over 12 hours?",
        }
        partial = MathSolution(problem="iv_rate", formula="iv_rate", volume_ml=None, hours=None)
        with mock.patch("agent.graph.complete_schema", return_value=partial):
            result = math_node(state)
        self.assertEqual(result["kind"], "answer")
        self.assertIn("83.33", result["checked_value"])

    def test_formula_follows_extracted_numbers(self) -> None:
        mislabeled = MathSolution(
            problem="How many tablets?",
            approach="dosage",
            formula="drip_rate",
            desired_dose=500,
            desired_unit="mg",
            have_dose=250,
            have_unit="mg",
            unsure_notes="none",
        )
        with mock.patch("agent.graph.complete_schema", return_value=mislabeled):
            result = math_node({"intent": "math", "request": "500 mg ordered, 250 mg tablets", "message": ""})
        self.assertIn("Result: 2 tablet", result["checked_value"])
        self.assertNotIn("Unsure", result["reply"])

    def test_equation_read_from_image_is_checked(self) -> None:
        empty = MathSolution(problem="3x + 5 = 20", approach="sympy", unsure_notes="none")
        state = {"intent": "math", "request": "Solve this", "message": "solve this", "vision_text": "Solve for x\n3x + 5 = 20"}
        with mock.patch("agent.graph.complete_schema", return_value=empty):
            result = math_node(state)
        self.assertEqual(result["kind"], "answer")
        self.assertIn("[5]", result["checked_value"])

    def test_math_without_numbers_asks(self) -> None:
        empty = MathSolution(problem="dose", approach="dosage")
        with mock.patch("agent.graph.complete_schema", return_value=empty):
            result = math_node({"intent": "math", "request": "Calculate the dose", "message": "calculate the dose"})
        self.assertEqual(result["kind"], "question")

    def test_vision_text_hides_empty_notes(self) -> None:
        reading = VisionReading(question_text="3x + 5 = 20", equations=["3x + 5 = 20"], diagram_notes="None")
        self.assertEqual(reading.as_text(), "3x + 5 = 20")

    def test_letter_request_gets_letter_format_and_length(self) -> None:
        guess = Understanding(intent="write", request="Write a 250-word leave letter to the teacher.", confidence=0.9)
        with mock.patch("agent.graph.complete_schema", return_value=guess):
            plan = plan_turn("Write a 250 word leave letter to my teacher, I was sick for 2 days", history=[])
        self.assertTrue(plan.needs_stream)
        self.assertIn("Format it as a letter", plan.system)
        self.assertIn("about 250 words", plan.system)
        self.assertEqual(plan.max_tokens, 900)

    def test_long_essay_gets_room_to_finish(self) -> None:
        guess = Understanding(intent="write", request="Write a 2000-word essay on asthma.", confidence=0.9)
        with mock.patch("agent.graph.complete_schema", return_value=guess):
            plan = plan_turn("Write a 2000 word essay on asthma", history=[])
        self.assertEqual(plan.max_tokens, 3500)
        self.assertIn("introduction with a clear thesis", plan.system)

    def test_write_and_export_in_one_message(self) -> None:
        guess = Understanding(intent="write", request="Write an asthma essay", confidence=0.9)
        with mock.patch("agent.graph.complete_schema", return_value=guess):
            plan = plan_turn("Write an essay on asthma and export it as pdf", history=[])
        self.assertTrue(plan.needs_stream)
        self.assertTrue(plan.also_export)
        self.assertEqual(plan.formats, ["pdf"])


if __name__ == "__main__":
    unittest.main()
