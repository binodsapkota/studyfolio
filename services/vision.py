from __future__ import annotations

from agent.prompts import vision_system
from agent.schema import VisionReading
from services.ollama_client import complete_schema, vision_model

MAX_IMAGES = 3


def transcribe(images: list[bytes], caption: str) -> VisionReading:
    if not images:
        return VisionReading(question_text=caption)
    prompt = caption.strip() or "Read the question in this image."
    return complete_schema(
        vision_system(),
        prompt,
        VisionReading,
        model_name=vision_model(),
        images=images[:MAX_IMAGES],
        num_predict=900,
    )
