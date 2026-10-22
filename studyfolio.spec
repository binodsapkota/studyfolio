# PyInstaller build for Studyfolio.exe. Build with:  .\scripts\build-release.ps1
# Streamlit loads app.py from source at runtime, so the app's own modules are listed
# as hidden imports to pull them (and everything they import) into the bundle.
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules, copy_metadata

ROOT = Path(SPECPATH)
app_modules = [
    f"{package}.{path.stem}"
    for package in ("agent", "services", "exporters")
    for path in sorted((ROOT / package).glob("*.py"))
    if path.stem != "__init__"
]

datas = [
    (str(ROOT / "app.py"), "."),
    (str(ROOT / ".streamlit" / "config.toml"), ".streamlit"),
]
datas += collect_data_files("streamlit")
datas += copy_metadata("streamlit")
datas += collect_data_files("docx")
datas += collect_data_files("fpdf")

hiddenimports = app_modules
hiddenimports += collect_submodules("streamlit")
hiddenimports += collect_submodules("langgraph")
hiddenimports += collect_submodules("langchain_core")
hiddenimports += collect_submodules("langchain_ollama")

a = Analysis(
    [str(ROOT / "launcher.py")],
    pathex=[str(ROOT)],
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["tkinter", "matplotlib", "IPython", "pytest", "PyInstaller"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Studyfolio",
    console=True,
    upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name="Studyfolio", upx=False)
