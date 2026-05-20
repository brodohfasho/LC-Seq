# src/core/app_paths.py
"""
Resolve application directories for development and PyInstaller builds.
"""

from __future__ import annotations

import sys
from pathlib import Path


def is_frozen() -> bool:
    """True when running as a PyInstaller-built executable."""
    return bool(getattr(sys, "frozen", False))


def get_application_root() -> Path:
    """
    Writable root for config/, output/, and logs/.

    Development: repository root (parent of ``src``).
    Frozen: directory containing ``LC-Seq.exe`` (not the ``_internal`` bundle).
    """
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent.parent


def resolve_user_path(path: str | Path) -> Path:
    """
    Resolve a path that may be relative to the application root.

    Args:
        path: File or directory path from settings (absolute or relative).

    Returns:
        Absolute resolved path.
    """
    p = Path(path)
    if p.is_absolute():
        return p
    return get_application_root() / p
