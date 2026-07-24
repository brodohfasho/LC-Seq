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
    "networkx",
    "reportlab",
    "scipy",
    "scipy.stats",
    "scipy.optimize",
    "scipy.signal",
]


def _collect_package(name: str) -> None:
    """Force-include a package's data, binaries, and submodules."""
    pkg_datas, pkg_binaries, pkg_hiddenimports = collect_all(name)
    datas.extend(pkg_datas)
    binaries.extend(pkg_binaries)
    hiddenimports.extend(pkg_hiddenimports)


try:
    import customtkinter  # noqa: F401

    _collect_package("customtkinter")
except ImportError as exc:
    raise SystemExit(
        "customtkinter is not installed in this Python environment. "
        "Activate your venv and run: pip install -r requirements.txt"
    ) from exc

_collect_package("matplotlib")

# Runtime scientific / export deps. collect_all avoids missing pure-Python modules
# (scipy.stats, networkx, openpyxl) that Analysis may only partially discover.
for _pkg in ("scipy", "networkx", "openpyxl", "reportlab", "xlrd"):
    try:
        __import__(_pkg)
    except ImportError as exc:
        raise SystemExit(
            f"{_pkg} is not installed in this Python environment. "
            "Activate your venv and run: pip install -r requirements.txt"
        ) from exc
    _collect_package(_pkg)

try:
    import lcseq  # noqa: F401

    _collect_package("lcseq")
    hiddenimports += ["lcseq", "lcseq._native", "lcseq.render"]
except ImportError as exc:
    raise SystemExit(
        "lcseq extension is not installed in this venv. "
        "Run .\\scripts\\build_windows.ps1 (builds via maturin) or "
        "maturin develop --release in LC-Seq-New-master — see dev/BUILD.md."
    ) from exc

help_dir = project_root / "src" / "help"
if help_dir.is_dir():
    datas += [
        (str(help_dir / name), "src/help")
        for name in help_dir.iterdir()
        if name.is_file()
    ]

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
        "pytest",
        "test",
        "tests",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

# UPX frequently corrupts scipy/numpy/binary extensions on Windows — leave off.
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="LC-Seq",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
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
    upx=False,
    upx_exclude=[],
    name="LC-Seq",
)
