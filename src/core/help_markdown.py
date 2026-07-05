# src/core/help_markdown.py
"""
Render markdown help topics into a CustomTkinter textbox with styled tags.

Supports the subset used in ``src/help/*.md``: headings, bold, inline code,
bullet lists, block quotes, horizontal rules, and pipe tables.
"""

from __future__ import annotations

import re
from typing import Iterable, Sequence, Tuple

import customtkinter as ctk

BlockTag = Tuple[str, ...]
InlinePattern = Tuple[re.Pattern[str], str]

_HEADING = re.compile(r"^(#{1,4})\s+(.*)$")
_LIST_ITEM = re.compile(r"^(\s*)([-*•]|\d+\.)\s+(.*)$")
_BLOCKQUOTE = re.compile(r"^>\s?(.*)$")
_TABLE_ROW = re.compile(r"^\|.+\|$")
_TABLE_SEP = re.compile(r"^\|[\s\-:|]+\|$")
_HRULE = re.compile(r"^-{3,}\s*$")

_INLINE_PATTERNS: Tuple[InlinePattern, ...] = (
    (re.compile(r"\*\*(.+?)\*\*"), "bold"),
    (re.compile(r"`([^`]+)`"), "code"),
)

_TAG_OPTIONS: dict[str, dict] = {
    "h1": {"font": ("Segoe UI", 18, "bold"), "spacing1": 10, "spacing3": 6},
    "h2": {"font": ("Segoe UI", 15, "bold"), "spacing1": 8, "spacing3": 4},
    "h3": {"font": ("Segoe UI", 13, "bold"), "spacing1": 6, "spacing3": 3},
    "h4": {"font": ("Segoe UI", 12, "bold"), "spacing1": 4, "spacing3": 2},
    "body": {"font": ("Segoe UI", 13), "spacing1": 2, "spacing3": 2},
    "bold": {"font": ("Segoe UI", 13, "bold")},
    "code": {"font": ("Consolas", 12)},
    "table": {"font": ("Consolas", 11), "spacing1": 0, "spacing3": 0},
    "quote": {"font": ("Segoe UI", 12, "italic"), "lmargin1": 18, "lmargin2": 18},
    "bullet": {"font": ("Segoe UI", 13), "lmargin1": 18, "lmargin2": 32},
    "hr": {"font": ("Segoe UI", 13)},
    "related": {"font": ("Segoe UI", 12, "bold"), "spacing1": 10, "spacing3": 4},
}


def configure_help_text_tags(textbox: ctk.CTkTextbox) -> None:
    """Register styled tags on a help textbox (idempotent)."""
    tk_text = textbox._textbox
    for name, options in _TAG_OPTIONS.items():
        tk_text.tag_configure(name, **options)


def render_markdown_to_textbox(textbox: ctk.CTkTextbox, markdown: str) -> None:
    """Replace textbox contents with rendered markdown."""
    configure_help_text_tags(textbox)
    textbox.configure(state="normal")
    textbox.delete("1.0", "end")

    lines = markdown.splitlines()
    index = 0
    while index < len(lines):
        line = lines[index]
        stripped = line.strip()

        if not stripped:
            textbox.insert("end", "\n")
            index += 1
            continue

        if _HRULE.match(stripped):
            textbox.insert("end", "─" * 48 + "\n", ("hr",))
            index += 1
            continue

        heading = _HEADING.match(stripped)
        if heading:
            level = len(heading.group(1))
            tag = f"h{min(level, 4)}"
            _insert_inline(textbox, heading.group(2), (tag,))
            textbox.insert("end", "\n")
            index += 1
            continue

        if _TABLE_ROW.match(stripped):
            table_lines: list[str] = []
            while index < len(lines) and _TABLE_ROW.match(lines[index].strip()):
                row = lines[index].strip()
                if not _TABLE_SEP.match(row):
                    table_lines.append(row)
                index += 1
            _insert_table(textbox, table_lines)
            textbox.insert("end", "\n")
            continue

        quote = _BLOCKQUOTE.match(stripped)
        if quote:
            _insert_inline(textbox, quote.group(1), ("quote",))
            textbox.insert("end", "\n")
            index += 1
            continue

        bullet = _LIST_ITEM.match(line)
        if bullet:
            textbox.insert("end", "• ", ("bullet",))
            _insert_inline(textbox, bullet.group(3), ("bullet",))
            textbox.insert("end", "\n")
            index += 1
            continue

        if stripped.startswith("— ") and "Related topics" in stripped:
            textbox.insert("end", stripped + "\n", ("related",))
            index += 1
            continue

        _insert_inline(textbox, stripped, ("body",))
        textbox.insert("end", "\n")
        index += 1

    textbox.configure(state="disabled")
    textbox.see("1.0")


def _insert_table(textbox: ctk.CTkTextbox, rows: Sequence[str]) -> None:
    """Render pipe tables in a monospace block."""
    if not rows:
        return
    parsed = [_split_table_row(row) for row in rows]
    widths = _column_widths(parsed)
    for cells in parsed:
        parts = []
        for col_idx, cell in enumerate(cells):
            width = widths[col_idx] if col_idx < len(widths) else 0
            parts.append(cell.ljust(width))
        textbox.insert("end", "  ".join(parts).rstrip() + "\n", ("table",))


def _split_table_row(row: str) -> list[str]:
    inner = row.strip().strip("|")
    return [re.sub(r"\*\*(.+?)\*\*", r"\1", cell.strip()) for cell in inner.split("|")]


def _column_widths(rows: Iterable[Sequence[str]]) -> list[int]:
    widths: list[int] = []
    for row in rows:
        for idx, cell in enumerate(row):
            while len(widths) <= idx:
                widths.append(0)
            widths[idx] = max(widths[idx], len(cell))
    return widths


def _insert_inline(textbox: ctk.CTkTextbox, text: str, base_tags: BlockTag) -> None:
    """Insert a line with inline ``**bold**`` and ``code`` spans."""
    if not text:
        return
    pattern = re.compile(r"(\*\*.+?\*\*|`[^`]+`)")
    pos = 0
    for match in pattern.finditer(text):
        if match.start() > pos:
            textbox.insert("end", text[pos : match.start()], base_tags)
        token = match.group(0)
        if token.startswith("**"):
            textbox.insert("end", token[2:-2], base_tags + ("bold",))
        else:
            textbox.insert("end", token[1:-1], base_tags + ("code",))
        pos = match.end()
    if pos < len(text):
        textbox.insert("end", text[pos:], base_tags)
