# tests/test_help_markdown.py
"""Tests for in-app markdown help rendering."""

from __future__ import annotations

import customtkinter as ctk

from src.core.help_content import format_help_with_related, load_help_text
from src.core.help_markdown import render_markdown_to_textbox


def test_render_markdown_applies_heading_and_bold_tags() -> None:
    root = ctk.CTk()
    root.withdraw()
    textbox = ctk.CTkTextbox(root, width=400, height=300)
    sample = "## Section\n\n**Bold term** and `code`.\n"
    render_markdown_to_textbox(textbox, sample)
    content = textbox.get("1.0", "end")
    assert "Section" in content
    assert "Bold term" in content
    assert "code" in content
    assert "h2" in textbox._textbox.tag_names("1.0")
    assert "bold" in textbox._textbox.tag_names("3.0")
    assert textbox._textbox.tag_nextrange("code", "3.0", "4.0")
    root.destroy()


def test_render_peak_picking_help_topic() -> None:
    root = ctk.CTk()
    root.withdraw()
    textbox = ctk.CTkTextbox(root, width=600, height=500)
    render_markdown_to_textbox(textbox, format_help_with_related("peak_picking"))
    content = textbox.get("1.0", "end")
    assert "Peak picking" in content
    assert "Modern" in content
    assert "Related topics" in content
    assert "h2" in textbox._textbox.tag_names("1.0") or "h1" in textbox._textbox.tag_names("1.0")
    assert len(load_help_text("peak_picking")) > 100
    root.destroy()


def test_new_getting_started_topics_render() -> None:
    root = ctk.CTk()
    root.withdraw()
    textbox = ctk.CTkTextbox(root, width=600, height=500)
    for topic_id in ("library_analysis", "del_library_setup"):
        render_markdown_to_textbox(textbox, format_help_with_related(topic_id))
        content = textbox.get("1.0", "end")
        assert len(content.strip()) > 50
        assert "Related topics" in content
    root.destroy()


def test_table_renders_as_embedded_widgets() -> None:
    root = ctk.CTk()
    root.withdraw()
    textbox = ctk.CTkTextbox(root, width=600, height=500)
    sample = (
        "## Table\n\n"
        "| Col A | Col B |\n"
        "|-------|-------|\n"
        "| one | two |\n"
        "| three | four |\n"
    )
    render_markdown_to_textbox(textbox, sample)
    embedded = textbox._textbox.window_names()
    assert embedded, "expected an embedded table widget"
    root.destroy()


def test_rerender_clears_previous_embedded_tables() -> None:
    root = ctk.CTk()
    root.withdraw()
    textbox = ctk.CTkTextbox(root, width=600, height=500)
    table_md = "| A | B |\n|---|---|\n| 1 | 2 |\n"
    render_markdown_to_textbox(textbox, table_md)
    first = len(textbox._textbox.window_names())
    render_markdown_to_textbox(textbox, table_md)
    second = len(textbox._textbox.window_names())
    assert first == second, "embedded tables should not accumulate across renders"
    root.destroy()
