from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
# The packaged app sets STUDYFOLIO_HOME so chats, exports, and .env live next to Studyfolio.exe.
HOME = Path(os.environ.get("STUDYFOLIO_HOME") or PROJECT_ROOT)
CONVERSATIONS = HOME / "conversations"
OUTPUTS = HOME / "outputs"
ENV_FILE = HOME / ".env"


def load_env() -> None:
    load_dotenv(ENV_FILE)
