"""Starts Studyfolio: makes sure Ollama and the models are ready, then serves the app and opens the browser.

This is the entry point of Studyfolio.exe. From source it also works as `python launcher.py`.
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

FROZEN = getattr(sys, "frozen", False)
BUNDLE = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
APP_FOLDER = Path(sys.executable).resolve().parent if FROZEN else BUNDLE
INSTALLER_URL = "https://ollama.com/download/OllamaSetup.exe"
DEFAULT_ENV = (
    "OLLAMA_BASE_URL=http://127.0.0.1:11434\n"
    "OLLAMA_MODEL=llama3.1:8b\n"
    "OLLAMA_VISION_MODEL=qwen2.5vl:3b\n"
)
MODEL_SIZES = {"llama3.1:8b": "4.9 GB", "qwen2.5vl:3b": "3.2 GB"}
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
DETACHED = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)


class SetupError(RuntimeError):
    pass


def say(text: str = "") -> None:
    print(text, flush=True)


def ask(question: str) -> bool:
    if not sys.stdin or not sys.stdin.isatty():
        return True
    try:
        answer = input(f"{question} [Y/n] ").strip().lower()
    except EOFError:
        return True
    return answer in ("", "y", "yes")


def data_home() -> Path:
    """Next to the exe when that folder is writable, otherwise %LOCALAPPDATA%\\Studyfolio."""
    for folder in (APP_FOLDER, Path(os.environ.get("LOCALAPPDATA", Path.home())) / "Studyfolio"):
        try:
            folder.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryFile(dir=folder):
                pass
            return folder
        except OSError:
            continue
    raise SetupError("Studyfolio could not find a folder it is allowed to write to.")


def read_env(path: Path) -> dict[str, str]:
    if not path.exists():
        path.write_text(DEFAULT_ENV, encoding="utf-8")
    values = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip().strip("\"'")
    return values


def ollama_get(base: str, route: str, timeout: float = 3) -> dict | None:
    try:
        with urllib.request.urlopen(base + route, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError):
        return None


def wait_for_ollama(base: str, seconds: int) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if ollama_get(base, "/api/version") is not None:
            return True
        time.sleep(1.5)
    return False


def find_ollama() -> Path | None:
    found = shutil.which("ollama")
    candidates = [Path(found)] if found else []
    candidates += [
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Ollama" / "ollama.exe",
        Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Ollama" / "ollama.exe",
    ]
    return next((path for path in candidates if path.is_file()), None)


def download(url: str, target: Path) -> None:
    with urllib.request.urlopen(url, timeout=60) as response, open(target, "wb") as handle:
        total = int(response.headers.get("Content-Length") or 0)
        done = 0
        while chunk := response.read(1 << 20):
            handle.write(chunk)
            done += len(chunk)
            if total:
                print(f"\r  {done / total:6.1%} of {total / 1e6:.0f} MB", end="", flush=True)
    say()


def signed_by_ollama(path: Path) -> bool:
    script = (
        f"$s = Get-AuthenticodeSignature -FilePath '{path}'; "
        "if ($s.Status -eq 'Valid' -and $s.SignerCertificate.Subject -match 'Ollama') { 'ok' }"
    )
    result = subprocess.run(
        ["powershell", "-NoProfile", "-Command", script], capture_output=True, text=True, creationflags=NO_WINDOW
    )
    return result.stdout.strip() == "ok"


def install_ollama() -> Path:
    say("Ollama runs the AI model on this computer. It is not installed yet.")
    if not ask("Download and install Ollama now (about 1 GB)?"):
        raise SetupError("Install Ollama from https://ollama.com/download, then start Studyfolio again.")
    installer = Path(tempfile.gettempdir()) / "OllamaSetup.exe"
    say(f"Downloading {INSTALLER_URL}")
    download(INSTALLER_URL, installer)
    if not signed_by_ollama(installer):
        installer.unlink(missing_ok=True)
        raise SetupError("The downloaded installer is not signed by Ollama, so it was not run.")
    say("Installing Ollama for this Windows user. This takes a minute or two.")
    marker = Path(os.environ.get("LOCALAPPDATA", "")) / "Ollama" / "upgraded"
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.touch()
    code = subprocess.run([str(installer), "/VERYSILENT", "/NORESTART", "/SUPPRESSMSGBOXES"]).returncode
    installer.unlink(missing_ok=True)
    found = find_ollama()
    if code != 0 or not found:
        raise SetupError(f"The Ollama installer did not finish (exit code {code}). Install it from https://ollama.com/download.")
    return found


def ensure_ollama(base: str) -> Path | None:
    if ollama_get(base, "/api/version") is not None:
        return find_ollama()
    if not base.startswith(("http://127.0.0.1", "http://localhost")):
        raise SetupError(f"Ollama is not answering at {base}. Check OLLAMA_BASE_URL in .env.")
    ollama = find_ollama() or install_ollama()
    say("Starting Ollama...")
    tray_app = ollama.with_name("ollama app.exe")
    command = [str(tray_app)] if tray_app.is_file() else [str(ollama), "serve"]
    subprocess.Popen(command, creationflags=NO_WINDOW | DETACHED, close_fds=True)
    if not wait_for_ollama(base, 60):
        raise SetupError("Ollama did not start. Open Ollama from the Start menu, then start Studyfolio again.")
    return ollama


def installed_models(base: str) -> set[str]:
    tags = ollama_get(base, "/api/tags") or {}
    names = set()
    for model in tags.get("models", []):
        name = model.get("name", "")
        names.update({name, name.removesuffix(":latest")})
    return names


def pull(base: str, model: str) -> None:
    body = json.dumps({"model": model, "stream": True}).encode()
    request = urllib.request.Request(base + "/api/pull", body, {"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=3600) as response:
        for line in response:
            event = json.loads(line or b"{}")
            if event.get("error"):
                raise SetupError(f"Downloading {model} failed: {event['error']}. Updating Ollama usually fixes this.")
            total, done = event.get("total"), event.get("completed")
            if total and done:
                print(f"\r  {model}: {done / total:6.1%} of {total / 1e9:.1f} GB   ", end="", flush=True)
    say(f"\r  {model}: done{' ' * 30}")


def ensure_models(base: str, text_model: str, vision_model: str) -> None:
    have = installed_models(base)
    if text_model not in have:
        size = MODEL_SIZES.get(text_model, "several GB")
        say(f"Studyfolio needs the text model {text_model} ({size}). This is a one-time download.")
        if not ask(f"Download {text_model} now?"):
            raise SetupError(f"Studyfolio cannot answer without {text_model}.")
        pull(base, text_model)
    if vision_model and vision_model not in have:
        size = MODEL_SIZES.get(vision_model, "a few GB")
        say(f"Reading images (screenshots, photos of questions) needs {vision_model} ({size}).")
        if ask(f"Download {vision_model} now? You can skip it and still ask text questions."):
            pull(base, vision_model)


def free_port(preferred: int = 8501) -> int:
    for port in [preferred, *range(preferred + 1, preferred + 50)]:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            if probe.connect_ex(("127.0.0.1", port)) != 0:
                return port
    raise SetupError("No free port between 8501 and 8550.")


def open_browser_when_ready(url: str) -> None:
    for _ in range(120):
        try:
            urllib.request.urlopen(url + "/_stcore/health", timeout=1)
            webbrowser.open(url)
            return
        except OSError:
            time.sleep(0.5)


def serve(home: Path) -> None:
    port = free_port()
    url = f"http://127.0.0.1:{port}"
    os.environ["STUDYFOLIO_HOME"] = str(home)
    os.chdir(BUNDLE)
    say()
    say(f"Studyfolio is running at {url}")
    say(f"Chats and exports are saved in {home}")
    say("Keep this window open while you use Studyfolio. Close it to stop.")
    threading.Thread(target=open_browser_when_ready, args=(url,), daemon=True).start()

    from streamlit.web import cli as streamlit_cli

    sys.argv = [
        "streamlit", "run", str(BUNDLE / "app.py"),
        "--global.developmentMode=false",
        "--server.headless=true",
        "--server.address=127.0.0.1",
        f"--server.port={port}",
        "--server.fileWatcherType=none",
        "--browser.gatherUsageStats=false",
    ]
    streamlit_cli.main()


def main() -> int:
    say("Studyfolio - local study tutor")
    say("=" * 31)
    try:
        home = data_home()
        env = read_env(home / ".env")
        base = env.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/")
        ensure_ollama(base)
        ensure_models(base, env.get("OLLAMA_MODEL", "llama3.1:8b"), env.get("OLLAMA_VISION_MODEL", "qwen2.5vl:3b"))
        serve(home)
    except KeyboardInterrupt:
        return 0
    except (SetupError, urllib.error.URLError, OSError) as error:
        say()
        say(f"Studyfolio could not start: {error}")
        if sys.stdin and sys.stdin.isatty():
            input("Press Enter to close this window.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
