from __future__ import annotations

import json
import re
import shutil
import time
import uuid
from datetime import datetime
from pathlib import Path

from services.paths import CONVERSATIONS

DATA = CONVERSATIONS
SETTINGS_FILE = DATA / "settings.json"
_ID = re.compile(r"^[a-f0-9]{12}$")
_index_cache: dict[str, tuple[float, dict]] = {}


def now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def new_id() -> str:
    return uuid.uuid4().hex[:12]


def new_conversation(title: str = "New chat") -> dict:
    stamp = now()
    return {
        "id": new_id(),
        "title": title,
        "created": stamp,
        "updated": stamp,
        "messages": [],
        "pending": None,
    }


def title_from(text: str, fallback: str = "New chat") -> str:
    words = re.sub(r"\s+", " ", text).strip()
    if not words:
        return fallback
    return words if len(words) <= 48 else words[:45].rstrip() + "…"


def _path(conversation_id: str) -> Path:
    return DATA / f"{conversation_id}.json"


def save(conversation: dict) -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    conversation["updated"] = now()
    target = _path(conversation["id"])
    payload = json.dumps(conversation, ensure_ascii=False, indent=1)
    temporary = target.with_suffix(".tmp")
    temporary.write_text(payload, encoding="utf-8")
    # Windows refuses the swap while a scanner or file watcher has the target open.
    for attempt in range(6):
        try:
            temporary.replace(target)
            return
        except PermissionError:
            time.sleep(0.05 * (attempt + 1))
    target.write_text(payload, encoding="utf-8")
    temporary.unlink(missing_ok=True)


def load(conversation_id: str | None) -> dict | None:
    if not conversation_id or not _ID.match(conversation_id):
        return None
    path = _path(conversation_id)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def list_recent(limit: int = 200) -> list[dict]:
    if not DATA.exists():
        return []
    items: list[dict] = []
    for path in DATA.glob("*.json"):
        if not _ID.match(path.stem):
            continue
        mtime = path.stat().st_mtime
        cached = _index_cache.get(path.stem)
        if cached and cached[0] == mtime:
            items.append(cached[1])
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        entry = {
            "id": payload.get("id", path.stem),
            "title": payload.get("title") or "New chat",
            "updated": payload.get("updated") or payload.get("created") or now(),
        }
        _index_cache[path.stem] = (mtime, entry)
        items.append(entry)
    items.sort(key=lambda item: item["updated"], reverse=True)
    return items[:limit]


def rename(conversation_id: str, title: str) -> None:
    conversation = load(conversation_id)
    if conversation is None or not title.strip():
        return
    conversation["title"] = title.strip()[:80]
    save(conversation)


def delete(conversation_id: str) -> None:
    if not _ID.match(conversation_id):
        return
    _path(conversation_id).unlink(missing_ok=True)
    shutil.rmtree(DATA / conversation_id, ignore_errors=True)
    _index_cache.pop(conversation_id, None)


def save_attachment(conversation_id: str, name: str, data: bytes) -> str:
    folder = DATA / conversation_id
    folder.mkdir(parents=True, exist_ok=True)
    suffix = Path(name).suffix.lower() or ".png"
    relative = f"{conversation_id}/{new_id()}{suffix}"
    (DATA / relative).write_bytes(data)
    return relative


def attachment_path(relative: str) -> Path:
    return DATA / relative


def load_settings() -> dict:
    try:
        return json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def save_settings(settings: dict) -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    SETTINGS_FILE.write_text(json.dumps(settings, ensure_ascii=False, indent=1), encoding="utf-8")
