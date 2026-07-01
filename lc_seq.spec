# lc_seq.spec
# PyInstaller spec for LC-Seq (Windows). Build from repo root with venv + requirements.txt active.

from pathlib import Path

from PyInstaller.utils.hooks import collect_all

block_cipher = None
project_root = Path(SPECPATH)

datas = []
binaries = []
hiddenimports = [
    "matplotlib.backends.backend_tkagg",
    "pandas",
    "openpyxl",
    "xlrd",
    "sqlite3",
    "customtkinter",
    "darkdetect",
]

try:
    import customtkinter

    ctk_datas, ctk_binaries, ctk_hiddenimports = collect_all("customtkinter")
    datas += ctk_datas
    binaries += ctk_binaries
    hiddenimports += ctk_hiddenimports
except ImportError as exc:
    raise SystemExit(
        "customtkinter is not installed in this Python environment. "
        "Activate your venv and run: pip install -r requirements.txt"
    ) from exc

mpl_datas, mpl_binaries, mpl_hiddenimports = collect_all("matplotlib")
datas += mpl_datas
binaries += mpl_binaries
hiddenimports += mpl_hiddenimports

help_dir = project_root / "src" / "help"
if help_dir.is_dir():
    datas += [(str(help_dir / name), "src/help") for name in help_dir.iterdir() if name.is_file()]

a = Analysis(
    [str(project_root / "src" / "main.py")],
    pathex=[str(project_root)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[str(project_root / "scripts" / "pyi_rth_mpl_tkagg.py")],
    excludes=[
        "PyQt6",
        "PyQt5",
        "PySide6",
        "PySide2",
        "matplotlib.tests",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="LC-Seq",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="LC-Seq",
)
