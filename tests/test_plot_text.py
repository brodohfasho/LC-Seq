# tests/test_plot_text.py
"""Tests for plot text sanitization."""

from __future__ import annotations

from src.core.plot_text import sanitize_plot_text


def test_sanitize_plot_text_strips_control_chars() -> None:
    raw = f"BB{chr(31)}Name"
    assert sanitize_plot_text(raw) == "BB?Name"
