# tests/test_help_content.py
"""Tests for bundled in-app help topics (Phase 6)."""

from __future__ import annotations

from pathlib import Path

from src.core.help_content import (
    HELP_TOPICS,
    format_help_with_related,
    get_help_topic,
    list_help_topics,
    load_help_text,
)


def test_all_help_topics_have_files() -> None:
    help_dir = Path(__file__).resolve().parents[1] / "src" / "help"
    for topic in HELP_TOPICS:
        path = help_dir / topic.filename
        assert path.is_file(), f"Missing help file for {topic.topic_id}: {topic.filename}"


def test_list_help_topics_matches_registry() -> None:
    topics = list_help_topics()
    assert len(topics) == len(HELP_TOPICS)
    assert topics[0].topic_id == "peak_picking"


def test_load_help_text_peak_picking() -> None:
    text = load_help_text("peak_picking")
    assert len(text) > 100
    assert "peak" in text.lower()


def test_related_topics_footer() -> None:
    body = format_help_with_related("peak_picking")
    assert "Related topics" in body
    for related_id in get_help_topic("peak_picking").related:  # type: ignore[union-attr]
        related = get_help_topic(related_id)
        assert related is not None
        assert related.title in body


def test_unknown_topic_returns_message() -> None:
    assert get_help_topic("not_a_topic") is None
    assert "Unknown help topic" in load_help_text("not_a_topic")
