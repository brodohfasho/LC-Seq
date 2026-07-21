# tests/test_ui_messages.py
"""Tests for shared UI message helpers (no Tk dialogs required)."""

from __future__ import annotations

from src.core.bb_index_csv import validate_bb_index_map
from src.core.pedigree_render import (
    graphviz_missing_banner,
    graphviz_missing_export_prompt,
)
from src.ui.ui_messages import _compose


def test_compose_appends_what_to_do() -> None:
    text = _compose("Something failed.", what_to_do="Try again after fixing X.")
    assert "Something failed." in text
    assert "What to do:" in text
    assert "Try again after fixing X." in text


def test_compose_without_tip() -> None:
    assert _compose("Only message.") == "Only message."


def test_encoding_mismatch_flag_on_validation() -> None:
    beta = "\u03b2Homoleu"
    result = validate_bb_index_map(
        {"?Homoleu": 17},
        [beta],
        null_token="AgxNull",
    )
    assert not result.ok
    assert result.likely_encoding_mismatch
    assert "encoding" in result.summary.lower() or "UTF-8" in " ".join(result.notes)


def test_graphviz_messages_mention_pedigree_and_matplotlib() -> None:
    banner = graphviz_missing_banner()
    assert "Graphviz" in banner
    assert "matplotlib" in banner.lower()
    assert "pedigree" in banner.lower()
    prompt = graphviz_missing_export_prompt()
    assert "Continue" in prompt
    assert "matplotlib" in prompt.lower()
