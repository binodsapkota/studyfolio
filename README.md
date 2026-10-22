# Studyfolio

Studyfolio is a private AI study tutor that runs entirely on your own Windows computer. It works like a chat app: it answers college questions (including nursing coursework), writes essays, letters, and emails, checks math and dosage with Python, reads screenshots, and exports Word, PDF, and Excel files. [Ollama](https://ollama.com) runs the Llama model locally, so nothing is sent to a cloud API.

- [Download and run (Windows)](#download-and-run-windows): for users. No Python needed.
- [Run from source](#run-from-source): for developers.
- [Build the exe yourself](#build-the-exe-yourself)

## Download and run (Windows)

### What you need

| | Minimum | Recommended |
|---|---|---|
| Windows | 10 or 11, 64-bit | 11 |
| RAM | 8 GB (slow) | 16 GB or more |
| Free disk space | 12 GB | 20 GB on an SSD |
| Graphics | Not required | NVIDIA GPU with 8 GB VRAM, or Intel Arc (see [Speed](#speed)) |
| Internet | First start only, to download Ollama and the models (about 9 GB in total) | |

### Step 1: Download

1. Open the [latest release](https://github.com/binodsapkota/studyfolio/releases/latest).
2. Under **Assets**, download `Studyfolio-<version>-windows-x64.zip` (about 90 MB).
3. Optional: check the download against the `.sha256` file next to it:

   ```powershell
   Get-FileHash .\Studyfolio-1.0.0-windows-x64.zip -Algorithm SHA256
   ```

### Step 2: Unzip

Right-click the zip, choose **Extract All**, and extract it to a folder you can write to, such as `Documents\Studyfolio`. Don't run the app from inside the zip, and avoid `C:\Program Files`. Your chats and exports are saved next to the app.

### Step 3: Start Studyfolio

Open the extracted `Studyfolio` folder and double-click **`Studyfolio.exe`**.

Windows may show **"Windows protected your PC"** the first time, because the app isn't code-signed. Click **More info**, then **Run anyway**.

A console window opens and sets everything up:

1. **Ollama.** If Ollama isn't installed, it asks: `Download and install Ollama now (about 1 GB)? [Y/n]`. Press **Enter**. It downloads the official installer from ollama.com, checks that the installer is signed by Ollama, and installs it for your Windows user.
2. **Models.** It asks to download `llama3.1:8b` (4.9 GB, required) and `qwen2.5vl:3b` (3.2 GB, only for reading images). Press **Enter** for each. A progress bar shows the download. Depending on your connection this takes 10-40 minutes. If it's interrupted, start the app again and it picks up where it stopped.
3. **App.** It prints `Studyfolio is running at http://127.0.0.1:8501` and opens your browser.

Keep the console window open while you use Studyfolio. Closing it stops the app.

### Every start after that

Double-click `Studyfolio.exe`. It starts in a few seconds without downloading anything. The first answer after a restart takes longer while the model loads into memory.

### Where your files go

| What | Where |
|---|---|
| Exported Word, PDF, and Excel files | `outputs\` next to `Studyfolio.exe`, plus a download button in the chat |
| Saved chats and pasted images | `conversations\` next to `Studyfolio.exe` |
| Model settings | `.env` next to `Studyfolio.exe` |
| AI models | Ollama's folder (`%USERPROFILE%\.ollama\models`) |

If the app folder isn't writable, chats, exports, and settings go to `%LOCALAPPDATA%\Studyfolio` instead.

### Updating

Download the new zip, extract it, and copy your `conversations` folder (and `.env` if you changed it) from the old folder into the new one. The models stay installed in Ollama, so there's nothing to download again.

### Uninstalling

Delete the Studyfolio folder. To also remove the models and Ollama, run `ollama rm llama3.1:8b` and `ollama rm qwen2.5vl:3b`, then uninstall Ollama from **Settings > Apps**.

## How to use it

- Type a question, or paste a screenshot with **Ctrl+V** (anywhere on the page), drop it, or attach it with **+**, then keep typing your message. Follow-up questions can refer back to the image.
- Ask for writing: "Write a 300-word essay on hand hygiene", "Write a leave letter to my teacher for Oct 23-24, I have a fever", "Draft an email to my professor asking for an extension". Then revise it: "make it more formal", "shorter".
- Ask for math: "How many mL/hr is 1,000 mL over 8 hours?" or "solve 3x + 5 = 20". Answers are checked with Python.
- Ask for a file only when you want one: "export it as PDF", "save as Word", or "export to Excel" (Excel needs a table in the answer).
- Recent chats are in the sidebar. Rename or delete them from the `⋯` menu. The settings button next to the name sets your course (General or Nursing), citation style, and custom instructions.

## What it does

- Works like a chat app: answers stream into the conversation, and recent chats are saved in the sidebar.
- Answers a typed question or an image.
- Drafts essays, outlines, reflections, care plans, concept maps, teaching plans, and practice SBAR notes, and revises them when you ask ("make it shorter").
- Writes letters (leave, complaint, cover, recommendation), emails, statements, resumes, memos, speeches, stories, poems, and posts in the right format. It follows your instructions on length ("300 words", "2 pages"), tone, audience, and structure, and uses `[placeholders]` instead of inventing names, dates, or addresses. If the request is missing who it's for or what it's about, it asks first.
- Checks grammar on text you paste or on an uploaded `.txt`, `.docx`, or `.pdf`.
- Checks algebra and calculus with SymPy, and dosage problems (tablets, mg/kg, mL/hr, gtt/min, reconstitution) with fixed formulas.
- Builds tables in the chat.

Before acting, Studyfolio works out what you mean from the whole conversation. When a request is vague or missing something it needs (no topic, no numbers, nothing to fix), it asks a short question, often with quick-reply buttons, instead of guessing.

Files are created only when you ask. If you say "export" without a format, Studyfolio asks which one.

Dosage answers and care plans are study drafts. They are not for giving a medication or writing a real chart. The tutor does not invent citations.

## Speed

Text questions, writing, grammar, and tables use `llama3.1:8b`. Image questions use `qwen2.5vl:3b`. Both run on the CPU when there's no supported GPU. That works on a 16 GB laptop, but replies come out at a few words per second.

- **NVIDIA GPU:** Ollama uses it automatically.
- **Intel Arc or other integrated graphics (Core Ultra laptops):** Ollama skips these by default. Set the Windows user environment variable `OLLAMA_IGPU_ENABLE=1`, quit Ollama from the system tray, and start Studyfolio again. `ollama ps` should then show `100% GPU`. On a Core Ultra 7 155H this made `llama3.1:8b` read prompts about 4x faster and write replies about 1.7x faster.

Newer Ollama versions no longer run `llama3.2-vision`. If you change `OLLAMA_VISION_MODEL` in `.env`, pick a vision model your Ollama version supports.

## Troubleshooting

| Problem | Fix |
|---|---|
| "Windows protected your PC" | Click **More info**, then **Run anyway**. |
| The console closes right away | Open a terminal in the Studyfolio folder and run `.\Studyfolio.exe` to read the error. |
| "Ollama did not start" | Open **Ollama** from the Start menu, wait a few seconds, and start Studyfolio again. |
| A model download fails | Start Studyfolio again; it resumes. If it keeps failing, update Ollama from [ollama.com/download](https://ollama.com/download). |
| The sidebar says the vision model is missing | Run `ollama pull qwen2.5vl:3b`, or restart Studyfolio and accept the download. |
| The browser didn't open | Open the address printed in the console, usually http://127.0.0.1:8501. |
| Antivirus quarantines `Studyfolio.exe` | PyInstaller apps are sometimes flagged by mistake. Restore the file and add an exception, or [run from source](#run-from-source). |
| Replies are very slow | See [Speed](#speed). Close other heavy programs. The first reply after a restart is always slower. |

## Run from source

You need Windows 64-bit, [Python 3.10+](https://www.python.org/downloads/), and Git.

```powershell
git clone https://github.com/binodsapkota/studyfolio.git
cd studyfolio
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
```

Install Ollama and the models with the included script. Add `-SkipModels` to skip the roughly 8 GB of model downloads, or `-InstallDir "D:\Ollama"` to choose the install folder:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\install-ollama.ps1
```

Then start the app either way:

```powershell
streamlit run app.py      # plain Streamlit, http://localhost:8501
python launcher.py        # the same checks and startup as Studyfolio.exe
```

`OLLAMA_MODEL`, `OLLAMA_VISION_MODEL`, and `OLLAMA_BASE_URL` in `.env` change the models and the Ollama address.

### Checks

```powershell
python -m unittest discover -s tests
```

These checks cover dosage, SymPy, exports, the export and clarification rules, writing-request parsing, and the agent paths that run without a model. They don't need Ollama.

## Build the exe yourself

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\build-release.ps1 -Version 1.0.0
```

The script installs `requirements-build.txt` (which adds PyInstaller), runs the unit tests, builds `dist\Studyfolio\Studyfolio.exe` from `studyfolio.spec`, and writes `release\Studyfolio-1.0.0-windows-x64.zip` with a `.sha256` file. To publish it:

```powershell
gh release create v1.0.0 release\Studyfolio-1.0.0-windows-x64.zip release\Studyfolio-1.0.0-windows-x64.zip.sha256 --title "Studyfolio 1.0.0"
```

How the package works: `launcher.py` is the exe's entry point. It picks the data folder (next to the exe, or `%LOCALAPPDATA%\Studyfolio`), sets `STUDYFOLIO_HOME`, makes sure Ollama is running and the models are present, then starts Streamlit on `127.0.0.1` (so other computers on the network can't reach it) and opens the browser.

## Project layout

```
app.py               Streamlit chat UI
launcher.py          Entry point for Studyfolio.exe (setup checks, then starts the app)
agent/               LangGraph agent: intent, prompts, routing, Markdown-to-document conversion
services/            Ollama client, chat storage, exports, math and dosage checks, file reading
exporters/           Word, PDF, and Excel writers
scripts/             Ollama installer and release build scripts
docs/START-HERE.txt  Quick-start guide shipped inside the release zip
studyfolio.spec      PyInstaller build definition
tests/               Unit tests
```
