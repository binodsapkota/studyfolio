from __future__ import annotations

import html
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import streamlit as st

from agent.format import with_line_breaks
from agent.graph import TurnPlan, export_after_reply, plan_turn, stream_reply
from agent.prompts import clip
from services import store
from services.ingest import extract_text
from services.ollama_client import OllamaError, model_ready, ollama_status, text_model, vision_model

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}
TEXT_SUFFIXES = {".txt", ".md", ".docx", ".pdf"}
FILE_TYPES = ["png", "jpg", "jpeg", "webp", "txt", "md", "docx", "pdf"]
MAX_IMAGES = 3
MAX_IMAGE_BYTES = 8_000_000
COURSES = ["General", "Nursing"]
SETTING_DEFAULTS = {"course": "General", "citation_style": "APA", "instructions": ""}
SUGGESTIONS = (
    ("Explain a concept", "Explain how to prioritize patients using the ABCs."),
    ("Check my math", "How many mL/hr is 1,000 mL over 8 hours?"),
    ("Draft an assignment", "Write a care plan for a patient with pneumonia."),
    ("Proofread text", "Proofread: The patient are resting comfortable after there surgery."),
)

PASTE_BRIDGE = """
<script>
(() => {
  if (window.__studyfolioPaste) return;
  window.__studyfolioPaste = true;
  document.addEventListener("paste", (event) => {
    const box = document.querySelector('[data-testid="stChatInputTextArea"]');
    const data = event.clipboardData;
    if (!box || !data || event.target === box) return;
    const target = event.target;
    const tag = (target && target.tagName || "").toLowerCase();
    if (tag === "input" || tag === "textarea" || (target && target.isContentEditable)) return;
    const files = Array.from(data.files || []);
    if (!files.length) return;
    event.preventDefault();
    const transfer = new DataTransfer();
    files.forEach((file) => transfer.items.add(file));
    box.focus();
    box.dispatchEvent(new ClipboardEvent("paste", { clipboardData: transfer, bubbles: true, cancelable: true }));
  }, true);
})();
</script>
"""


def main() -> None:
    st.set_page_config(
        page_title="Studyfolio",
        page_icon=":material/school:",
        layout="centered",
        initial_sidebar_state="expanded",
    )
    _init_state()
    _styles()
    _sidebar()
    queued = st.session_state.pop("queued", None)
    conversation = st.session_state.conversation
    messages = conversation["messages"] if conversation else []
    if not messages and not queued:
        _home()
        return
    _thread(messages, interactive=queued is None)
    _composer()
    if queued:
        _handle(queued)


def _init_state() -> None:
    if "conversation" not in st.session_state:
        st.session_state.conversation = store.load(st.query_params.get("c"))
    if "settings_loaded" not in st.session_state:
        saved = store.load_settings()
        for key, default in SETTING_DEFAULTS.items():
            st.session_state[key] = saved.get(key, default)
        if st.session_state.course not in COURSES:
            st.session_state.course = "General"
        st.session_state.settings_loaded = True


def _settings() -> dict:
    return {key: st.session_state.get(key, default) for key, default in SETTING_DEFAULTS.items()}


def _save_settings() -> None:
    store.save_settings(_settings())


# Sidebar


@st.cache_data(ttl=10, show_spinner=False)
def _cached_status() -> tuple[bool, tuple[str, ...]]:
    reachable, names = ollama_status()
    return reachable, tuple(names)


def _sidebar() -> None:
    with st.sidebar:
        with st.container(horizontal=True, vertical_alignment="center", wrap=False, key="brand-row"):
            st.markdown('<div class="sf-brand">Studyfolio</div>', unsafe_allow_html=True)
            with st.popover("", icon=":material/tune:", type="tertiary", help="Settings", key="settings-menu"):
                _settings_panel()
        st.button(
            "New chat",
            icon=":material/edit_square:",
            key="new-chat",
            type="tertiary",
            width="stretch",
            on_click=_new_chat,
        )
        reachable, _ = _cached_status()
        if not reachable:
            st.warning("Ollama is not running. Start the Ollama app to chat.", icon=":material/power_off:")
        current = st.session_state.conversation["id"] if st.session_state.conversation else None
        for label, items in _grouped(store.list_recent()):
            st.markdown(f'<div class="sf-group">{label}</div>', unsafe_allow_html=True)
            for item in items:
                _history_row(item, item["id"] == current)
        st.html(PASTE_BRIDGE, unsafe_allow_javascript=True)


def _settings_panel() -> None:
    st.markdown("**Settings**")
    st.selectbox("Course", COURSES, key="course", on_change=_save_settings)
    st.text_input("Citation style", key="citation_style", on_change=_save_settings)
    st.text_area(
        "Custom instructions",
        key="instructions",
        height=110,
        placeholder="For example: I'm a second-year nursing student. Keep answers short.",
        on_change=_save_settings,
    )
    reachable, names = _cached_status()
    installed = list(names)
    st.caption("Ollama is running" if reachable else "Ollama is not running")
    for name in (text_model(), vision_model()):
        state = "installed" if reachable and model_ready(name, installed) else "not installed"
        st.caption(f"{name}: {state}")


def _history_row(item: dict, active: bool) -> None:
    conversation_id = item["id"]
    key = f"row-{conversation_id}" + ("-active" if active else "")
    with st.container(horizontal=True, vertical_alignment="center", gap=None, wrap=False, key=key):
        st.button(
            item["title"],
            key=f"open-{conversation_id}",
            type="tertiary",
            width="stretch",
            on_click=_open,
            args=(conversation_id,),
        )
        with st.popover("", icon=":material/more_horiz:", type="tertiary", key=f"menu-{conversation_id}"):
            st.text_input(
                "Rename",
                value=item["title"],
                key=f"name-{conversation_id}",
                label_visibility="collapsed",
            )
            st.button(
                "Rename",
                icon=":material/edit:",
                key=f"rename-{conversation_id}",
                width="stretch",
                on_click=_rename,
                args=(conversation_id,),
            )
            st.button(
                "Delete",
                icon=":material/delete:",
                key=f"delete-{conversation_id}",
                width="stretch",
                on_click=_delete,
                args=(conversation_id,),
            )


def _grouped(items: list[dict]) -> list[tuple[str, list[dict]]]:
    today = date.today()
    order = ["Today", "Yesterday", "Previous 7 days", "Previous 30 days", "Older"]
    groups: dict[str, list[dict]] = {name: [] for name in order}
    for item in items:
        try:
            day = datetime.fromisoformat(item["updated"]).date()
        except ValueError:
            day = today
        age = (today - day).days
        if age <= 0:
            groups["Today"].append(item)
        elif age == 1:
            groups["Yesterday"].append(item)
        elif age <= 7:
            groups["Previous 7 days"].append(item)
        elif age <= 30:
            groups["Previous 30 days"].append(item)
        else:
            groups["Older"].append(item)
    return [(name, groups[name]) for name in order if groups[name]]


def _new_chat() -> None:
    st.session_state.conversation = None
    st.session_state.pop("queued", None)
    st.query_params.clear()


def _open(conversation_id: str) -> None:
    conversation = store.load(conversation_id)
    st.session_state.conversation = conversation
    if conversation:
        st.query_params["c"] = conversation_id
    else:
        st.query_params.clear()


def _rename(conversation_id: str) -> None:
    store.rename(conversation_id, st.session_state.get(f"name-{conversation_id}", ""))
    current = st.session_state.conversation
    if current and current["id"] == conversation_id:
        st.session_state.conversation = store.load(conversation_id)


def _delete(conversation_id: str) -> None:
    store.delete(conversation_id)
    current = st.session_state.conversation
    if current and current["id"] == conversation_id:
        _new_chat()


# Main area


def _home() -> None:
    st.markdown('<div class="sf-hero"><h1>What can I help with?</h1></div>', unsafe_allow_html=True)
    with st.container(key="home-composer"):
        _composer()
    with st.container(horizontal=True, horizontal_alignment="center", key="suggestions"):
        for index, (label, prompt) in enumerate(SUGGESTIONS):
            st.button(label, key=f"suggest-{index}", on_click=_queue_text, args=(prompt,))


def _composer() -> None:
    st.chat_input(
        "Ask anything. Paste or drop images too.",
        key="composer",
        accept_file="multiple",
        file_type=FILE_TYPES,
        max_upload_size=8,
        on_submit=_on_submit,
    )


def _on_submit() -> None:
    value = st.session_state.get("composer")
    if value is None:
        return
    if isinstance(value, str):
        text, files = value, []
    else:
        text, files = value.text or "", list(value.files or [])
    uploads = [{"name": upload.name or "image.png", "data": upload.getvalue()} for upload in files]
    if text.strip() or uploads:
        st.session_state.queued = {"text": text, "uploads": uploads}


def _queue_text(text: str) -> None:
    st.session_state.queued = {"text": text, "uploads": []}


def _thread(messages: list[dict], *, interactive: bool) -> None:
    last = len(messages) - 1
    for index, message in enumerate(messages):
        _render(message, is_last=interactive and index == last)


def _render(message: dict, *, is_last: bool) -> None:
    if message["role"] == "user":
        with st.chat_message("user"):
            paths = [store.attachment_path(item) for item in message.get("images", [])]
            paths = [str(path) for path in paths if path.exists()]
            if paths:
                st.image(paths, width=220)
            if message.get("files"):
                st.caption("  ".join(f":material/description: {html.escape(name)}" for name in message["files"]))
            if message.get("content"):
                st.markdown(with_line_breaks(message["content"]))
            if message.get("vision"):
                with st.expander("What I read from the image"):
                    st.markdown(message["vision"])
        return
    with st.chat_message("assistant"):
        st.markdown(with_line_breaks(message.get("content", "")))
        _render_exports(message)
        if is_last and message.get("options"):
            with st.container(horizontal=True, key=f"options-{message['id']}"):
                for index, option in enumerate(message["options"]):
                    st.button(option, key=f"option-{message['id']}-{index}", on_click=_queue_text, args=(option,))


def _render_exports(message: dict) -> None:
    records = message.get("exports") or []
    if not records:
        return
    with st.container(horizontal=True):
        for record in records:
            path = Path(record["path"])
            if not path.exists():
                st.caption(f"{record['file_name']} is no longer in the outputs folder.")
                continue
            st.download_button(
                f"Download {record['label']}",
                data=path.read_bytes(),
                file_name=record["file_name"],
                mime=record["mime"],
                icon=":material/download:",
                key=f"download-{message['id']}-{record['format']}",
                on_click="ignore",
            )


# One turn


def _handle(queued: dict) -> None:
    text = queued.get("text", "").strip()
    images, image_uploads, attachment_text, file_names, error = _read_uploads(queued.get("uploads", []))
    if not text and not images and not attachment_text and not error:
        return
    conversation = st.session_state.conversation
    if conversation is None:
        fallback = "Image question" if images else (file_names[0] if file_names else "New chat")
        conversation = store.new_conversation(store.title_from(text, fallback))
        st.session_state.conversation = conversation
        st.query_params["c"] = conversation["id"]
    history = list(conversation["messages"])
    pending = conversation.get("pending")
    user_message = {
        "id": store.new_id(),
        "role": "user",
        "content": text,
        "images": [store.save_attachment(conversation["id"], item["name"], item["data"]) for item in image_uploads],
        "files": file_names,
        "attachment_text": clip(attachment_text, 20000) if attachment_text else "",
        "created": store.now(),
    }
    conversation["messages"].append(user_message)
    conversation["pending"] = None
    store.save(conversation)
    _render(user_message, is_last=False)

    with st.chat_message("assistant"):
        if not error and images and not model_ready(vision_model()):
            error = f"To read images, install the vision model first: `ollama pull {vision_model()}`"
        if error:
            st.markdown(error)
            _append_assistant(conversation, error, kind="error")
        else:
            _respond(conversation, user_message, text, images, attachment_text, history, pending)
    store.save(conversation)
    st.rerun()


def _respond(
    conversation: dict,
    user_message: dict,
    text: str,
    images: list[bytes],
    attachment_text: str,
    history: list[dict],
    pending: dict | None,
) -> None:
    status = st.empty()
    body = st.empty()

    def progress(label: str) -> None:
        status.markdown(f'<div class="sf-thinking">{html.escape(label)}</div>', unsafe_allow_html=True)

    progress("Reading your image…" if images else "Thinking…")
    try:
        plan = plan_turn(
            text,
            images=images,
            attachment_text=attachment_text,
            history=history,
            pending=pending,
            settings=_settings(),
            on_progress=progress,
        )
        user_message["vision"] = plan.vision_text
        reply = _show_reply(plan, status, body)
    except OllamaError as exc:
        status.empty()
        _append_assistant(conversation, str(exc), kind="error")
        return
    except Exception as exc:
        status.empty()
        _append_assistant(conversation, f"Studyfolio couldn't finish that request: {exc}", kind="error")
        return
    if not reply.strip():
        _append_assistant(conversation, "I didn't get a reply from the model. Please try again.", kind="error")
        return
    answer = _append_assistant(
        conversation,
        reply,
        kind=plan.kind,
        intent=plan.intent,
        options=plan.options,
        exports=plan.exports,
    )
    conversation["pending"] = plan.pending
    if plan.also_export:
        outcome = export_after_reply(plan, reply, answer["id"])
        _append_assistant(
            conversation,
            outcome.reply,
            kind=outcome.kind,
            intent="export",
            options=outcome.options,
            exports=outcome.exports,
        )
        conversation["pending"] = outcome.pending


def _show_reply(plan: TurnPlan, status, body) -> str:
    if not plan.needs_stream:
        status.empty()
        body.markdown(with_line_breaks(plan.reply))
        return plan.reply

    text = ""
    shown_at = 0.0
    for chunk in stream_reply(plan):
        if not text:
            status.empty()
        text += chunk
        if time.monotonic() - shown_at > 0.05:
            body.markdown(with_line_breaks(text) + " ▌")
            shown_at = time.monotonic()
    body.markdown(with_line_breaks(text))
    return text


def _append_assistant(conversation: dict, content: str, *, kind: str = "answer", **extra) -> dict:
    message = {
        "id": store.new_id(),
        "role": "assistant",
        "content": content,
        "kind": kind,
        "created": store.now(),
    }
    message.update({key: value for key, value in extra.items() if value})
    conversation["messages"].append(message)
    return message


def _read_uploads(uploads: list[dict]) -> tuple[list[bytes], list[dict], str, list[str], str]:
    images: list[bytes] = []
    image_uploads: list[dict] = []
    texts: list[str] = []
    names: list[str] = []
    for upload in uploads or []:
        name = upload.get("name") or "image.png"
        data = upload.get("data") or b""
        suffix = Path(name).suffix.lower()
        if suffix in IMAGE_SUFFIXES:
            if len(data) > MAX_IMAGE_BYTES:
                return [], [], "", names + [name], "Each image must be 8 MB or smaller."
            if len(images) >= MAX_IMAGES:
                return [], [], "", names + [name], f"Attach up to {MAX_IMAGES} images per message."
            images.append(data)
            image_uploads.append({"name": name, "data": data})
            continue
        names.append(name)
        if suffix not in TEXT_SUFFIXES:
            return [], [], "", names, "Attach an image, or a .txt, .md, .docx, or .pdf file."
        try:
            texts.append(f"{name}\n{extract_text(name, data)}")
        except Exception as exc:
            return [], [], "", names, f"I couldn't read {name}: {exc}"
    return images, image_uploads, "\n\n".join(texts), names, ""


def _styles() -> None:
    st.markdown(
        """
        <style>
        header[data-testid="stHeader"] { background: transparent; }
        [data-testid="stDecoration"], footer, [data-testid="stAppDeployButton"],
        [data-testid="stHeaderActionElements"], .st-key-suggestions [data-stale="true"] { display: none; }
        [data-testid="stSidebar"] [data-testid="stPopoverButton"] div[aria-hidden="true"] { display: none; }
        [data-testid="stMainBlockContainer"] { max-width: 48rem; padding-top: 2.5rem; padding-bottom: 7rem; }
        [data-testid="stBottomBlockContainer"] { max-width: 48rem; padding-bottom: 1.2rem; }

        /* Composer */
        [data-testid="stChatInput"] {
            background: #303030;
            border: 1px solid rgba(255,255,255,0.08);
            border-radius: 28px;
            box-shadow: 0 4px 24px rgba(0,0,0,0.25);
        }
        [data-testid="stChatInput"] > div { background: transparent; border: none; }
        [data-testid="stChatInputTextArea"] { font-size: 1rem; }

        /* Messages */
        [data-testid="stChatMessageAvatarUser"], [data-testid="stChatMessageAvatarAssistant"] { display: none; }
        [data-testid="stChatMessage"] { background: transparent; padding: 0.35rem 0; gap: 0; }
        [data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarUser"]) { justify-content: flex-end; }
        [data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarUser"]) [data-testid="stChatMessageContent"] {
            background: #303030;
            border-radius: 1.4rem;
            padding: 0.55rem 1.1rem;
            max-width: 78%;
            flex: 0 1 auto;
            width: auto;
            margin-left: auto;
            margin-right: 0;
        }
        [data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarUser"]) [data-testid="stImage"] img {
            border-radius: 0.8rem;
        }
        [data-testid="stChatMessageContent"] p, [data-testid="stChatMessageContent"] li { line-height: 1.65; }
        .sf-thinking {
            color: #9b9b9b;
            background: linear-gradient(90deg, #8f8f8f 0%, #ececec 50%, #8f8f8f 100%);
            background-size: 200% 100%;
            -webkit-background-clip: text;
            background-clip: text;
            -webkit-text-fill-color: transparent;
            animation: sf-shimmer 1.6s linear infinite;
            padding: 0.2rem 0;
        }
        @keyframes sf-shimmer { from { background-position: 200% 0; } to { background-position: 0 0; } }

        /* Home */
        .sf-hero { min-height: 30vh; display: flex; align-items: flex-end; justify-content: center; padding-bottom: 1.2rem; }
        .sf-hero h1 { font-size: 2rem; font-weight: 500; letter-spacing: -0.01em; margin: 0; padding: 0; }
        .st-key-suggestions { margin-top: 0.6rem; }
        .st-key-suggestions button, [class*="st-key-options-"] button {
            border-radius: 999px;
            border: 1px solid rgba(255,255,255,0.14);
            background: transparent;
            color: #d0d0d0;
        }
        .st-key-suggestions button:hover, [class*="st-key-options-"] button:hover { background: #2f2f2f; }

        /* Sidebar */
        [data-testid="stSidebarUserContent"] { padding-top: 0.5rem; }
        .sf-brand { font-weight: 600; font-size: 1.05rem; padding-left: 0.6rem; }
        .st-key-brand-row { justify-content: space-between; }
        .st-key-brand-row > div:first-child { flex: 1 1 auto; }
        .sf-group { color: #8e8e8e; font-size: 0.75rem; font-weight: 600; padding: 0.9rem 0.6rem 0.2rem; }
        [data-testid="stSidebarHeader"] { min-height: 2.75rem; height: 2.75rem; padding-top: 0.6rem; }
        [data-testid="stSidebar"] [class*="st-key-open-"] button,
        .st-key-new-chat button {
            width: 100%;
            justify-content: flex-start;
            padding: 0.4rem 0.6rem;
            border-radius: 0.6rem;
            color: #ececec;
            min-height: 2.1rem;
        }
        [data-testid="stSidebar"] [class*="st-key-open-"] button > div,
        [data-testid="stSidebar"] [class*="st-key-open-"] button > div > span,
        .st-key-new-chat button > div,
        .st-key-new-chat button > div > span {
            justify-content: flex-start; min-width: 0; max-width: 100%;
        }
        [data-testid="stSidebar"] button[data-testid="stBaseButton-tertiary"]:hover { color: #ffffff; }
        .st-key-new-chat button:hover { background: #262626; }
        [data-testid="stSidebar"] [class*="st-key-open-"] p,
        .st-key-new-chat p {
            white-space: nowrap; overflow: hidden; text-overflow: ellipsis; text-align: left; font-size: 0.9rem;
        }
        [data-testid="stSidebar"] [class*="st-key-row-"] { border-radius: 0.6rem; }
        [data-testid="stSidebar"] [class*="st-key-row-"]:hover { background: #212121; }
        [data-testid="stSidebar"] [class*="st-key-row-"][class*="-active"] { background: #2a2a2a; }
        [data-testid="stSidebar"] [class*="st-key-row-"] [data-testid="stPopover"] { opacity: 0; transition: opacity 0.15s; }
        [data-testid="stSidebar"] [class*="st-key-row-"]:hover [data-testid="stPopover"],
        [data-testid="stSidebar"] [class*="st-key-row-"][class*="-active"] [data-testid="stPopover"] { opacity: 1; }
        [data-testid="stSidebar"] [class*="st-key-row-"] [data-testid="stPopover"] button { padding: 0.3rem; min-height: 1.8rem; }
        [data-testid="stSidebar"] [class*="st-key-row-"] [class*="st-key-open-"] { min-width: 0; flex: 1 1 auto; }
        </style>
        """,
        unsafe_allow_html=True,
    )


if __name__ == "__main__":
    main()
