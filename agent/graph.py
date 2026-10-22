from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable, Iterator, TypedDict

from langgraph.graph import END, StateGraph

from agent.intent import (
    export_formats,
    export_requested,
    fix_typos,
    format_list,
    is_affirmative,
    is_export_command,
    is_small_talk,
    mentions_export,
    missing_topic,
    requested_words,
    topic_question,
    writing_kind,
)
from agent.prompts import clip, compose_system, math_system, understand_system
from agent.schema import STUDY_NOTE, MathSolution, Understanding
from services.dosage import DosageError, compute_dosage, format_number
from services.exporting import export_markdown
from services.math_solver import MathCheckError, evaluate_expression
from services.ollama_client import NUM_CTX, OllamaError, complete_schema, stream_chat
from services.vision import transcribe

WORK_INTENTS = {"explain", "math", "write", "grammar", "table"}
FORMULAS = {"tablets", "weight_based", "iv_rate", "drip_rate", "reconstitution"}
MAX_OUTPUT_TOKENS = 4500
DEFAULT_TEMPERATURE = 0.3
CREATIVE_TEMPERATURE = 0.7
_VOLUME = re.compile(r"(\d[\d,]*(?:\.\d+)?)\s*(ml|l)\b", re.IGNORECASE)
_DURATION = re.compile(r"(\d+(?:\.\d+)?)\s*(hours?|hrs?|h|minutes?|mins?)\b", re.IGNORECASE)
_EQUATION = re.compile(r"[0-9A-Za-z+\-*/^(). ]+=[0-9A-Za-z+\-*/^(). ]+")
FORMAT_QUESTION = "Which format would you like: Word, PDF, or Excel?"
FORMAT_OPTIONS = ["Word", "PDF", "Excel"]
DEFAULT_QUESTION = "Could you tell me a bit more about what you'd like me to do?"
CLARIFY_BELOW = 0.35
HISTORY_CHAR_BUDGET = 14000


class GraphState(TypedDict, total=False):
    message: str
    images: list[bytes]
    attachment_text: str
    history: list[dict]
    pending: dict | None
    settings: dict
    vision_text: str
    intent: str
    request: str
    question: str
    options: list[str]
    formats: list[str]
    also_export: bool
    target_id: str
    reply: str
    kind: str
    pending_out: dict | None
    exports: list[dict]
    checked_value: str
    check_error: str
    system: str
    turns: list[tuple[str, str]]
    max_tokens: int
    temperature: float


@dataclass
class TurnPlan:
    intent: str
    request: str = ""
    vision_text: str = ""
    reply: str = ""
    kind: str = "answer"
    options: list[str] = field(default_factory=list)
    pending: dict | None = None
    exports: list[dict] = field(default_factory=list)
    checked_value: str = ""
    check_error: str = ""
    system: str = ""
    turns: list[tuple[str, str]] = field(default_factory=list)
    formats: list[str] = field(default_factory=list)
    also_export: bool = False
    max_tokens: int = 1600
    temperature: float = 0.3

    @property
    def needs_stream(self) -> bool:
        return bool(self.system) and not self.reply


@dataclass
class ExportOutcome:
    reply: str
    kind: str
    exports: list[dict] = field(default_factory=list)
    options: list[str] = field(default_factory=list)
    pending: dict | None = None


def plan_turn(
    message: str,
    *,
    images: list[bytes] | None = None,
    attachment_text: str = "",
    history: list[dict] | None = None,
    pending: dict | None = None,
    settings: dict | None = None,
    on_progress: Callable[[str], None] | None = None,
) -> TurnPlan:
    state: GraphState = {
        "message": message.strip(),
        "images": images or [],
        "attachment_text": attachment_text.strip(),
        "history": history or [],
        "pending": pending,
        "settings": settings or {},
    }
    final: dict = dict(state)
    for chunk in _graph.stream(state, stream_mode="updates"):
        for node, update in chunk.items():
            if update:
                final.update(update)
            label = _progress_label(node, final)
            if on_progress and label:
                on_progress(label)
    return TurnPlan(
        intent=final.get("intent", "explain"),
        request=final.get("request", ""),
        vision_text=final.get("vision_text", ""),
        reply=final.get("reply", ""),
        kind=final.get("kind", "answer"),
        options=final.get("options", []),
        pending=final.get("pending_out"),
        exports=final.get("exports", []),
        checked_value=final.get("checked_value", ""),
        check_error=final.get("check_error", ""),
        system=final.get("system", ""),
        turns=final.get("turns", []),
        formats=final.get("formats", []),
        also_export=bool(final.get("also_export")),
        max_tokens=final.get("max_tokens", 1600),
        temperature=final.get("temperature", DEFAULT_TEMPERATURE),
    )


def stream_reply(plan: TurnPlan) -> Iterator[str]:
    return stream_chat(plan.system, plan.turns, num_predict=plan.max_tokens, temperature=plan.temperature)


def export_after_reply(plan: TurnPlan, reply: str, message_id: str) -> ExportOutcome:
    return export_outcome(reply, plan.formats, message_id, title_hint=plan.request)


def export_outcome(content: str, formats: list[str], target_id: str, *, title_hint: str = "") -> ExportOutcome:
    pending = {"type": "export_format", "target": target_id}
    if not formats:
        return ExportOutcome(FORMAT_QUESTION, "question", options=list(FORMAT_OPTIONS), pending=pending)
    records, skipped = export_markdown(content, formats, title_hint=title_hint)
    if not records:
        return ExportOutcome(
            "That answer doesn't have a table to put in Excel. "
            "Do you want it as Word or PDF instead, or should I turn it into a table first?",
            "question",
            options=["Word", "PDF", "Make it a table"],
            pending=pending,
        )
    made = [record["format"] for record in records]
    noun = "file is" if len(made) == 1 else "files are"
    reply = f"Your {format_list(made)} {noun} ready."
    if skipped:
        reply += " That answer has no table, so I didn't make an Excel file."
    return ExportOutcome(reply, "export", exports=records)


def vision_node(state: GraphState) -> GraphState:
    images = state.get("images") or []
    if not images:
        return {"vision_text": ""}
    reading = transcribe(images, state.get("message", ""))
    return {"vision_text": reading.as_text()}


def understand_node(state: GraphState) -> GraphState:
    message = state.get("message", "")
    pending = state.get("pending") or {}
    has_attachment = bool(state.get("images") or state.get("attachment_text"))

    if pending.get("type") == "export_format":
        formats = export_formats(message)
        if formats:
            return _export_intent(formats, pending.get("target", ""))
    if pending.get("type") == "confirm_export" and is_affirmative(message):
        return _export_intent(export_formats(message), pending.get("target", ""))
    if not has_attachment and is_export_command(message):
        return _export_intent(export_formats(message), "")
    if not has_attachment and is_small_talk(message):
        return {"intent": "chat", "request": message}

    try:
        understanding = complete_schema(
            understand_system(),
            _understand_prompt(state),
            Understanding,
            num_predict=300,
        )
    except OllamaError as exc:
        if "not running" in str(exc) or "not installed" in str(exc):
            raise
        understanding = Understanding(intent="explain", request=message, confidence=0.5)

    intent = understanding.intent
    question = understanding.question.strip()
    options = [option.strip() for option in understanding.options if option.strip()][:4]
    pending_out = None
    asked_for_file = export_requested(message)
    if intent == "export" and not asked_for_file:
        if mentions_export(message) and message.rstrip().endswith("?"):
            intent = "explain"
        else:
            intent = "clarify"
            question = "Do you want me to export the last answer as a file?"
            options = ["Yes, as Word", "Yes, as PDF", "No"]
            pending_out = {"type": "confirm_export", "target": ""}
    elif intent != "clarify" and understanding.confidence < CLARIFY_BELOW and question:
        intent = "clarify"
    elif intent in ("write", "table") and not state.get("history") and not has_attachment and missing_topic(message):
        question = topic_question(message, intent)
        intent = "clarify"
    if intent == "clarify" and not question:
        question = DEFAULT_QUESTION
    if intent != "clarify":
        question, options = "", []

    also_export = intent in WORK_INTENTS and asked_for_file
    formats = export_formats(message) if intent == "export" or also_export else []
    return {
        "intent": intent,
        "request": understanding.request.strip() or message,
        "question": question,
        "options": options,
        "pending_out": pending_out,
        "formats": formats,
        "also_export": also_export,
        "target_id": "",
    }


def clarify_node(state: GraphState) -> GraphState:
    return {
        "reply": state.get("question") or DEFAULT_QUESTION,
        "kind": "question",
        "options": state.get("options", []),
        "pending_out": state.get("pending_out"),
    }


def export_node(state: GraphState) -> GraphState:
    target = _find_target(state.get("history", []), state.get("target_id", ""))
    if target is None:
        return {
            "reply": "There's no answer to export yet. What would you like me to write first?",
            "kind": "question",
            "options": [],
            "pending_out": None,
        }
    outcome = export_outcome(
        target.get("content", ""),
        state.get("formats", []),
        target.get("id", ""),
        title_hint=_asked_before(state.get("history", []), target),
    )
    return {
        "reply": outcome.reply,
        "kind": outcome.kind,
        "options": outcome.options,
        "pending_out": outcome.pending,
        "exports": outcome.exports,
    }


def math_node(state: GraphState) -> GraphState:
    solution = complete_schema(math_system(), _math_prompt(state), MathSolution, num_predict=900)
    _fill_rate_fields(
        solution,
        [state.get("request", ""), state.get("message", ""), state.get("vision_text", "")],
    )
    solution.formula = _infer_formula(solution)
    problem_texts = [
        state.get("vision_text", ""),
        state.get("message", ""),
        state.get("request", ""),
        state.get("attachment_text", ""),
    ]
    if solution.formula == "none" and not solution.expressions:
        solution.expressions = _equations_from(problem_texts)
    if not solution.problem.strip() or solution.problem.strip().lower() in FORMULAS:
        solution.problem = state.get("request") or state.get("message") or "Problem"
    checked, error = _check_math(solution)
    if not checked and not solution.steps:
        if not any(re.search(r"\d", text or "") for text in problem_texts):
            detail = solution.unsure_notes.strip() if _meaningful(solution.unsure_notes) else ""
            return {
                "reply": (
                    "I need a bit more information to work this out. "
                    + (f"{detail} " if detail else "")
                    + "Could you give me all the numbers and units in the problem?"
                ),
                "kind": "question",
                "options": [],
            }
        fallback = compose_node({**state, "intent": "explain"})
        fallback["system"] += (
            "\n\nSolve the problem step by step and state the final answer clearly. Python could not "
            "check this answer, so end with the line: _Not checked with Python._"
        )
        return fallback
    return {
        "reply": _math_reply(solution, checked, error),
        "kind": "answer",
        "checked_value": checked,
        "check_error": error,
    }


def compose_node(state: GraphState) -> GraphState:
    settings = state.get("settings", {})
    intent = state.get("intent", "explain")
    message, request = state.get("message", ""), state.get("request", "")
    kind, target_words = "general", None
    if intent == "write":
        kind = writing_kind(message, request, _last_user_text(state.get("history", [])))
        target_words = requested_words(message, state.get("attachment_text", ""), request)
    max_tokens = _output_budget(intent, target_words)
    system = compose_system(
        intent,
        course=settings.get("course", "General"),
        citation_style=settings.get("citation_style", "APA"),
        instructions=settings.get("instructions", ""),
        request=request,
        kind=kind,
        target_words=target_words,
    )
    # Prompt and reply share one context window, so long pieces get less history.
    history_chars = max(3000, min(HISTORY_CHAR_BUDGET, (NUM_CTX - max_tokens - 1500) * 3))
    turns = _history_turns(state.get("history", []), history_chars)
    turns.append(("user", _current_user_text(state)))
    return {
        "system": system,
        "turns": turns,
        "kind": "chat" if intent == "chat" else "answer",
        "max_tokens": max_tokens,
        "temperature": CREATIVE_TEMPERATURE if kind in ("poem", "story", "speech") else DEFAULT_TEMPERATURE,
    }


def _output_budget(intent: str, target_words: int | None) -> int:
    if intent == "write":
        if target_words:
            return max(900, min(MAX_OUTPUT_TOKENS, int(target_words * 1.6) + 300))
        return 3000
    if intent == "grammar":
        return 3000
    return 1600


def _last_user_text(history: list[dict]) -> str:
    for item in reversed(history):
        if item.get("role") == "user" and item.get("content"):
            return item["content"]
    return ""


def _export_intent(formats: list[str], target_id: str) -> GraphState:
    return {
        "intent": "export",
        "request": "Export the latest answer.",
        "formats": formats,
        "target_id": target_id,
        "also_export": False,
        "pending_out": None,
    }


def _find_target(history: list[dict], target_id: str) -> dict | None:
    if target_id:
        for message in history:
            if message.get("id") == target_id:
                return message
    for message in reversed(history):
        if message.get("role") == "assistant" and message.get("kind", "answer") == "answer":
            return message
    return None


def _asked_before(history: list[dict], target: dict) -> str:
    """The user's question that led to an answer, used to name its export."""
    index = next((i for i, item in enumerate(history) if item is target), len(history))
    for item in reversed(history[:index]):
        if item.get("role") == "user" and item.get("content", "").strip():
            return clip(item["content"].strip().rstrip("?.!"), 60).replace("\n[truncated]", "")
    return ""


def _user_text(message: dict, limit: int) -> str:
    parts = [message.get("content", "").strip() or "(no text)"]
    if message.get("vision"):
        parts.append("[Image content, read by the vision model]\n" + clip(message["vision"], limit))
    if message.get("attachment_text"):
        parts.append("[Attached file text]\n" + clip(message["attachment_text"], limit))
    return "\n".join(parts)


def _understand_prompt(state: GraphState) -> str:
    lines = ["Conversation so far:"]
    recent = [item for item in state.get("history", []) if item.get("kind") != "error"][-8:]
    if not recent:
        lines.append("(none)")
    for item in recent:
        if item.get("role") == "user":
            lines.append("User: " + _user_text(item, 400))
        else:
            lines.append("Assistant: " + clip(item.get("content", ""), 600))
    lines.append("")
    lines.append("Newest user message: " + (fix_typos(state.get("message", "")) or "(no text)"))
    if state.get("images"):
        lines.append("The user attached an image. Its content:\n" + (state.get("vision_text") or "(unreadable)"))
    if state.get("attachment_text"):
        lines.append("Attached file text:\n" + clip(state["attachment_text"], 1500))
    return "\n".join(lines)


def _history_turns(history: list[dict], char_budget: int = HISTORY_CHAR_BUDGET) -> list[tuple[str, str]]:
    turns: list[tuple[str, str]] = []
    used = 0
    for item in reversed([entry for entry in history if entry.get("kind") != "error"]):
        if item.get("role") == "user":
            text = _user_text(item, 1500)
        else:
            text = clip(item.get("content", ""), 3000)
        if used + len(text) > char_budget and turns:
            break
        turns.append(("user" if item.get("role") == "user" else "assistant", text))
        used += len(text)
    turns.reverse()
    while turns and turns[0][0] != "user":
        turns.pop(0)
    return turns


def _current_user_text(state: GraphState) -> str:
    parts = [state.get("message") or "(The user sent an attachment without text.)"]
    if state.get("vision_text"):
        parts.append("[Image content, read by the vision model]\n" + state["vision_text"])
    if state.get("attachment_text"):
        parts.append("[Attached file text]\n" + clip(state["attachment_text"], 6000))
    return "\n\n".join(parts)


def _math_prompt(state: GraphState) -> str:
    parts = []
    recent = [item for item in state.get("history", []) if item.get("kind") != "error"][-4:]
    if recent:
        context = []
        for item in recent:
            speaker = "User" if item.get("role") == "user" else "Assistant"
            text = _user_text(item, 400) if item.get("role") == "user" else clip(item.get("content", ""), 500)
            context.append(f"{speaker}: {text}")
        parts.append("Earlier conversation:\n" + "\n".join(context))
    if state.get("request"):
        parts.append("Problem to solve: " + state["request"])
    if state.get("attachment_text"):
        parts.append("Attached file text:\n" + clip(state["attachment_text"], 3000))
    if state.get("vision_text"):
        parts.append("Text read from the image:\n" + state["vision_text"])
    parts.append("Student message:\n" + clip(state.get("message", "") or "(see the image)"))
    return "\n\n".join(parts)


def _fill_rate_fields(solution: MathSolution, texts: list[str]) -> None:
    """The model sometimes picks an IV formula but drops the volume or time; take them from the text."""
    if solution.formula not in ("iv_rate", "drip_rate") and solution.problem.strip().lower() not in ("iv_rate", "drip_rate"):
        return
    for text in texts:
        if solution.volume_ml is None:
            volume = _VOLUME.search(text or "")
            if volume:
                solution.volume_ml = float(volume.group(1).replace(",", ""))
                solution.volume_unit = "L" if volume.group(2).lower() == "l" else "mL"
        if not (solution.hours or solution.minutes):
            duration = _DURATION.search(text or "")
            if duration:
                amount = float(duration.group(1))
                if duration.group(2).lower().startswith("h"):
                    solution.hours = amount
                else:
                    solution.minutes = amount


def _equations_from(texts: list[str]) -> list[str]:
    """Turn a plain one-variable equation such as "3x + 5 = 20" into a SymPy solve call."""
    for text in texts:
        for line in (text or "").splitlines():
            candidate = line.strip().rstrip(".")
            if candidate.count("=") != 1 or not _EQUATION.fullmatch(candidate):
                continue
            variables = set(re.findall(r"[A-Za-z]+", candidate))
            if len(variables) != 1 or len(next(iter(variables))) != 1:
                continue
            left, right = (side.strip() for side in candidate.split("="))
            if left and right:
                return [f"solve(Eq({left}, {right}), {next(iter(variables))})"]
    return []


def _meaningful(note: str) -> bool:
    return note.strip().lower().strip(".") not in ("", "none", "n/a", "na", "nothing")


def _formula_inputs_present(solution: MathSolution, formula: str) -> bool:
    timed = bool(solution.hours or solution.minutes)
    return {
        "tablets": bool(solution.desired_dose and solution.have_dose),
        "weight_based": bool(solution.weight and solution.dose_per_kg),
        "iv_rate": bool(solution.volume_ml and timed),
        "drip_rate": bool(solution.volume_ml and timed and solution.drop_factor),
        "reconstitution": bool(solution.desired_dose and solution.concentration),
    }.get(formula, False)


def _infer_formula(solution: MathSolution) -> str:
    """Trust the numbers the model extracted over the formula label it picked."""
    named = solution.formula if solution.formula != "none" else solution.problem.strip().lower()
    if named in FORMULAS and _formula_inputs_present(solution, named):
        return named
    for formula in ("drip_rate", "iv_rate", "weight_based", "reconstitution", "tablets"):
        if _formula_inputs_present(solution, formula):
            return formula
    return solution.formula


def _check_math(solution: MathSolution) -> tuple[str, str]:
    if solution.formula != "none":
        try:
            result = compute_dosage(
                solution.formula,
                desired_dose=solution.desired_dose,
                desired_unit=solution.desired_unit,
                have_dose=solution.have_dose,
                have_unit=solution.have_unit,
                weight=solution.weight,
                weight_unit=solution.weight_unit,
                dose_per_kg=solution.dose_per_kg,
                dose_per_kg_unit=solution.dose_per_kg_unit,
                volume_ml=solution.volume_ml,
                volume_unit=solution.volume_unit,
                hours=solution.hours,
                minutes=solution.minutes,
                drop_factor=solution.drop_factor,
                concentration=solution.concentration,
                concentration_unit=solution.concentration_unit,
            )
        except DosageError as exc:
            return "", str(exc)
        detail = " ".join(result.details)
        checked = (
            f"{result.formula_shown}  \n{result.substitution}  \n"
            f"**Result: {format_number(result.value)} {result.unit}**  \n{detail}"
        )
        return checked.strip(), ""
    if solution.approach == "dosage":
        return "", "The model did not choose a dosage formula, so no dose was calculated."
    if not solution.expressions:
        return "", solution.unsure_notes or "No expression was available to check."
    lines: list[str] = []
    errors: list[str] = []
    for expression in solution.expressions:
        try:
            lines.append(f"`{expression}` = **{evaluate_expression(expression)}**")
        except MathCheckError as exc:
            errors.append(str(exc))
    return "  \n".join(lines), "\n".join(errors)


def _math_reply(solution: MathSolution, checked: str, error: str) -> str:
    lines = [f"**{solution.problem.strip()}**", ""]
    for index, step in enumerate(solution.steps, start=1):
        lines.append(f"{index}. {step}")
    if _meaningful(solution.unsure_notes):
        lines.extend(["", f"**Unsure:** {solution.unsure_notes.strip()}"])
    if checked:
        lines.extend(["", "**Checked with Python**", "", checked])
    elif error:
        lines.extend(["", f"**Not checked:** {error}"])
    lines.extend(["", f"_{STUDY_NOTE}_"])
    return "\n".join(lines).strip()


def _progress_label(node: str, state: dict) -> str:
    if node == "vision":
        return "Understanding your request…"
    if node == "understand":
        return {
            "math": "Working through the math…",
            "export": "Preparing your file…",
        }.get(state.get("intent", ""), "")
    return ""


def _route(state: GraphState) -> str:
    intent = state.get("intent", "explain")
    if intent in ("clarify", "export", "math"):
        return intent
    return "compose"


def _build_graph():
    graph = StateGraph(GraphState)
    graph.add_node("vision", vision_node)
    graph.add_node("understand", understand_node)
    graph.add_node("clarify", clarify_node)
    graph.add_node("export", export_node)
    graph.add_node("math", math_node)
    graph.add_node("compose", compose_node)
    graph.set_entry_point("vision")
    graph.add_edge("vision", "understand")
    graph.add_conditional_edges(
        "understand",
        _route,
        {"clarify": "clarify", "export": "export", "math": "math", "compose": "compose"},
    )
    for name in ("clarify", "export", "math", "compose"):
        graph.add_edge(name, END)
    return graph.compile()


_graph = _build_graph()
