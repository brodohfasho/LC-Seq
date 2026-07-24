# src/main.py
"""
Main entry point for LC-Seq application.

This is the primary entry point that launches the LC-Seq
chromatographic data analysis application.
"""

from __future__ import annotations

import sys
from pathlib import Path


def _smoke_imports() -> int:
    """
    Packaging check: import critical runtime deps and write a status file.

    Invoked as ``LC-Seq.exe --smoke-imports`` after PyInstaller builds.
    Runs before GUI imports so a broken UI stack cannot hide packaging gaps.
    """
    if getattr(sys, "frozen", False):
        out = Path(sys.executable).resolve().parent / "smoke_imports.txt"
    else:
        out = Path.cwd() / "smoke_imports.txt"

    checks = (
        ("lcseq", "import lcseq; from lcseq import find_peaks, evaluate_library"),
        ("scipy.stats", "from scipy.stats import nbinom, poisson"),
        ("scipy.signal", "from scipy.signal import find_peaks"),
        ("scipy.optimize", "from scipy.optimize import curve_fit"),
        ("networkx", "import networkx"),
        ("openpyxl", "from openpyxl import Workbook"),
        ("reportlab", "import reportlab"),
        ("pandas", "import pandas"),
    )
    lines: list[str] = []
    failed = False
    for name, code in checks:
        try:
            exec(code, {})
            lines.append(f"OK  {name}")
        except Exception as exc:  # noqa: BLE001 - report any import failure
            failed = True
            lines.append(f"FAIL {name}: {exc}")
    try:
        out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    except OSError as exc:
        # Last-resort path if the exe directory is somehow not writable.
        fallback = Path.cwd() / "smoke_imports.txt"
        fallback.write_text(
            "\n".join(lines + [f"FAIL write_primary: {exc}"]) + "\n",
            encoding="utf-8",
        )
        return 1
    return 1 if failed else 0


# Handle packaging smoke test before importing the GUI stack.
if __name__ == "__main__" and "--smoke-imports" in sys.argv:
    raise SystemExit(_smoke_imports())

# Repo root must be on sys.path before any ``src.*`` import when running from source.
# PyInstaller sets this up automatically when frozen.
if not getattr(sys, "frozen", False):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.core.app_paths import resolve_user_path

import customtkinter as ctk
from src.core.logging_config import setup_logging, get_logger
from src.core.app_state import AppState
from src.core.config_manager import ConfigManager
from src.ui.main_screen import MainScreen

# Set up logging
setup_logging()
logger = get_logger(__name__)


def main() -> int:
    """
    Main application entry point.

    Initializes the application and starts the main UI.
    """
    logger.info("LC-Seq application starting...")

    try:
        # Set customtkinter appearance mode and color theme
        ctk.set_appearance_mode("system")  # Use system theme
        ctk.set_default_color_theme("blue")  # Use blue color theme

        # Initialize core components
        app_state = AppState()
        config_manager = ConfigManager()

        # Load saved settings
        settings = config_manager.load_settings()
        log_file = settings.log_file
        if log_file:
            log_file = str(resolve_user_path(log_file))
        if settings.log_level:
            setup_logging(log_level=settings.log_level, log_file=log_file)

        # Create and run main screen
        app = MainScreen(app_state, config_manager)
        app.run()

        logger.info("LC-Seq application exiting")
        return 0

    except Exception as e:
        logger.critical(f"Fatal error in main: {e}", exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
