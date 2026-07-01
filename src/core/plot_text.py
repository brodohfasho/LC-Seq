# src/core/plot_text.py
"""Plot label sanitization and matplotlib font configuration."""

from __future__ import annotations

import unicodedata
from pathlib import Path

_font_configured = False


def sanitize_plot_text(text: str) -> str:
    """
    Remove control characters that DejaVu Sans cannot render (e.g. ASCII 31).

    User metadata sometimes contains unit separators or other non-printable bytes.
    """
    if not text:
        return text
    cleaned: list[str] = []
    for ch in text:
        if ch in ("\n", "\t"):
            cleaned.append(ch)
            continue
        code = ord(ch)
        if code < 32 or code == 127:
            cleaned.append("?")
            continue
        if unicodedata.category(ch) in ("Cc", "Cf"):
            cleaned.append("?")
            continue
        cleaned.append(ch)
    return "".join(cleaned)


def configure_plot_fonts() -> None:
    """
    Prefer widely available open-source / system sans-serif fonts for matplotlib.

    Bundled ``assets/fonts/NotoSans-Regular.ttf`` is registered when present so
    new installs do not need manual font installation.
    """
    global _font_configured
    if _font_configured:
        return

    import platform

    import matplotlib.pyplot as plt
    from matplotlib import font_manager

    candidates: list[str] = []
    assets_dir = Path(__file__).resolve().parents[1] / "assets" / "fonts"
    for font_file in (
        assets_dir / "NotoSans-Regular.ttf",
        assets_dir / "NotoSansDisplay-Regular.ttf",
    ):
        if font_file.is_file():
            font_manager.fontManager.addfont(str(font_file))
            family = font_manager.FontProperties(fname=str(font_file)).get_name()
            if family and family not in candidates:
                candidates.append(family)

    system = platform.system()
    if system == "Windows":
        candidates.extend(["Segoe UI", "DejaVu Sans", "Arial"])
    elif system == "Darwin":
        candidates.extend(["Helvetica Neue", "Arial", "DejaVu Sans"])
    else:
        candidates.extend(["DejaVu Sans", "Liberation Sans", "Arial"])

    seen: set[str] = set()
    ordered: list[str] = []
    for name in candidates:
        if name not in seen:
            seen.add(name)
            ordered.append(name)

    plt.rcParams["font.sans-serif"] = ordered + ["sans-serif"]
    plt.rcParams["axes.unicode_minus"] = False
    _font_configured = True
