from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from typing import Iterator, TypeVar

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_ollama import ChatOllama
from pydantic import BaseModel, ValidationError

from services.paths import load_env

T = TypeVar("T", bound=BaseModel)

# Every call to a model uses the same context size; Ollama reloads the model when it changes.
NUM_CTX = 8192
VISION_NUM_CTX = 4096
KEEP_ALIVE = "15m"


class OllamaError(RuntimeError):
    """Ollama is unavailable or returned something Studyfolio cannot use."""


def base_url() -> str:
    load_env()
    return os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/")


def text_model() -> str:
    load_env()
    return os.getenv("OLLAMA_MODEL", "llama3.1:8b")


def vision_model() -> str:
    load_env()
    return os.getenv("OLLAMA_VISION_MODEL", "qwen2.5vl:3b")


def ollama_status() -> tuple[bool, list[str]]:
    try:
        with urllib.request.urlopen(base_url() + "/api/tags", timeout=1) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
        return False, []
    names = [item.get("name", "") for item in payload.get("models", []) if item.get("name")]
    return True, names


def model_ready(name: str, installed: list[str] | None = None) -> bool:
    names = installed if installed is not None else ollama_status()[1]
    target = name.strip()
    for installed_name in names:
        if installed_name == target or installed_name.split(":")[0] == target:
            return True
    return False


def ollama_schema(model: type[BaseModel]) -> dict:
    schema = model.model_json_schema()
    defs = schema.pop("$defs", {})

    def walk(node):
        if isinstance(node, dict):
            if "$ref" in node:
                ref_name = node["$ref"].rsplit("/", 1)[-1]
                return walk(defs[ref_name])
            result = {key: walk(value) for key, value in node.items() if key != "$schema"}
            # Small models skip optional fields, so every field is required in the grammar.
            if isinstance(result.get("properties"), dict):
                result["required"] = list(result["properties"])
            return result
        if isinstance(node, list):
            return [walk(item) for item in node]
        return node

    return walk(schema)


def parse_model_json(text: str, model: type[T]) -> T:
    cleaned = text.strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start == -1 or end <= start:
        raise OllamaError("The model did not return JSON.")
    try:
        return model.model_validate_json(cleaned[start : end + 1])
    except ValidationError as exc:
        raise OllamaError("The model returned JSON in an unexpected shape.") from exc


def _require_model(name: str) -> None:
    reachable, installed = ollama_status()
    if not reachable:
        raise OllamaError("Ollama is not running. Start the Ollama app, then try again.")
    if not model_ready(name, installed):
        raise OllamaError(f"Model '{name}' is not installed. Run: ollama pull {name}")


def complete_schema(
    system: str,
    user: str,
    model: type[T],
    *,
    model_name: str | None = None,
    images: list[bytes] | None = None,
    num_predict: int = 1400,
) -> T:
    name = model_name or (vision_model() if images else text_model())
    _require_model(name)
    llm = ChatOllama(
        model=name,
        base_url=base_url(),
        temperature=0,
        num_predict=num_predict,
        num_ctx=NUM_CTX if name == text_model() else VISION_NUM_CTX,
        keep_alive=KEEP_ALIVE,
        format=ollama_schema(model),
    )
    if images:
        import base64

        blocks: list[dict] = [{"type": "text", "text": user}]
        for image in images[:3]:
            encoded = base64.b64encode(image).decode("ascii")
            blocks.append(
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/jpeg;base64,{encoded}"},
                }
            )
        messages = [SystemMessage(content=system), HumanMessage(content=blocks)]
    else:
        messages = [SystemMessage(content=system), HumanMessage(content=user)]
    try:
        response = llm.invoke(messages)
    except Exception as exc:
        if "unknown model architecture" in str(exc):
            role = "OLLAMA_VISION_MODEL" if images else "OLLAMA_MODEL"
            raise OllamaError(
                f"This version of Ollama can't run '{name}'. Pull a model it supports with "
                f"`ollama pull <model>`, then set {role} in .env to that model."
            ) from exc
        raise OllamaError(f"Ollama request failed: {exc}") from exc
    content = response.content if isinstance(response.content, str) else str(response.content)
    return parse_model_json(content, model)


def stream_chat(
    system: str,
    turns: list[tuple[str, str]],
    *,
    num_predict: int = 2048,
    temperature: float = 0.3,
) -> Iterator[str]:
    name = text_model()
    _require_model(name)
    llm = ChatOllama(
        model=name,
        base_url=base_url(),
        temperature=temperature,
        num_predict=num_predict,
        num_ctx=NUM_CTX,
        keep_alive=KEEP_ALIVE,
    )
    messages: list = [SystemMessage(content=system)]
    for role, content in turns:
        messages.append(HumanMessage(content=content) if role == "user" else AIMessage(content=content))
    try:
        for chunk in llm.stream(messages):
            text = chunk.content if isinstance(chunk.content, str) else ""
            if text:
                yield text
    except Exception as exc:
        raise OllamaError(f"Ollama request failed: {exc}") from exc
