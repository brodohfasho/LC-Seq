# src/core/database_library.py
"""
Managed SQLite database files for optional bulk processing (output/databases).
"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from pathlib import Path
from typing import List

logger = logging.getLogger(__name__)


def get_project_root() -> Path:
    """Return repository root (directory containing ``src``)."""
    return Path(__file__).resolve().parent.parent.parent


def get_databases_dir() -> Path:
    """Ensure ``output/databases`` exists and return its path."""
    d = get_project_root() / "output" / "databases"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _sanitize_stem(stem: str) -> str:
    """Make a filesystem-safe fragment from spreadsheet stem."""
    s = re.sub(r"[^\w.\-]+", "_", stem, flags=re.UNICODE).strip("._")
    return (s[:80] if s else "spreadsheet")


def sanitize_database_stem(stem: str) -> str:
    """
    Sanitize user- or spreadsheet-derived text for use in a database file name.

    Args:
        stem: Raw prefix (e.g. user label or spreadsheet base name).

    Returns:
        Safe fragment suitable for ``allocate_new_database_path``.
    """
    return _sanitize_stem(stem)


def allocate_new_database_path(spreadsheet_stem: str) -> Path:
    """
    Reserve a new unique ``.db`` path under the managed output folder.

    Args:
        spreadsheet_stem: Prefix for the file name (spreadsheet stem, user label, etc.).

    Returns:
        Absolute path for the new database file (file not created yet).
    """
    safe = _sanitize_stem(spreadsheet_stem)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    return get_databases_dir() / f"{safe}_{ts}.db"


def list_managed_databases() -> List[str]:
    """
    List ``.db`` files in the managed folder, sorted by name.

    Returns:
        Absolute paths as strings.
    """
    d = get_databases_dir()
    return sorted(str(p.resolve()) for p in d.glob("*.db") if p.is_file())


def delete_database_files(db_path: Path) -> bool:
    """
    Remove a SQLite database and common sidecar files (WAL, SHM).

    Args:
        db_path: Path to the primary ``.db`` file.

    Returns:
        True if the primary database file was removed or already absent.
    """
    db_path = Path(db_path)
    ok = True
    for suffix in ("", "-wal", "-shm"):
        path = Path(str(db_path) + suffix) if suffix else db_path
        try:
            if path.is_file():
                path.unlink()
                logger.info("Removed database file: %s", path)
        except OSError as exc:
            logger.warning("Could not remove %s: %s", path, exc)
            ok = False
    return ok
