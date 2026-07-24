# src/ui/ui_messages.py
"""
Shared user-facing dialog helpers for consistent errors, warnings, and prompts.

Use these instead of ad-hoc ``messagebox`` calls when the user needs a clear
cause and a next step (encoding, BB-index mismatch, missing Graphviz, etc.).
"""

from __future__ import annotations

from typing import Optional

from tkinter import messagebox

from src.core.bb_index_csv import BbIndexValidationResult, format_validation_report
from src.core.pedigree_render import (
    graphviz_available,
    graphviz_missing_banner,
    graphviz_missing_export_prompt,
)


def _compose(message: str, *, what_to_do: Optional[str] = None) -> str:
    text = (message or "").strip()
    tip = (what_to_do or "").strip()
    if tip:
        return f"{text}\n\nWhat to do:\n{tip}"
    return text


def show_error(
    parent,
    title: str,
    message: str,
    *,
    what_to_do: Optional[str] = None,
) -> None:
    """Blocking error: the user must fix something before continuing."""
    messagebox.showerror(title, _compose(message, what_to_do=what_to_do), parent=parent)


def show_warning(
    parent,
    title: str,
    message: str,
    *,
    what_to_do: Optional[str] = None,
) -> None:
    """Non-fatal warning: work may continue with degraded quality or gaps."""
    messagebox.showwarning(title, _compose(message, what_to_do=what_to_do), parent=parent)


def show_info(parent, title: str, message: str) -> None:
    """Informational notice."""
    messagebox.showinfo(title, (message or "").strip(), parent=parent)


def ask_continue(parent, title: str, message: str) -> bool:
    """Yes/No prompt; returns True when the user chooses to continue."""
    return bool(
        messagebox.askyesno(title, (message or "").strip(), parent=parent)
    )


def show_bb_index_validation_result(parent, result: BbIndexValidationResult) -> None:
    """
    Present BB-index validation with an explicit dialog (not only the textbox).

    Encoding mismatches and name mismatches use different titles and next steps.
    """
    report = format_validation_report(result)
    if result.ok:
        notes = "\n".join(f"• {note}" for note in result.notes)
        body = result.summary if not notes else f"{result.summary}\n\n{notes}"
        show_info(parent, "Building-block index", body)
        return

    if result.likely_encoding_mismatch:
        show_warning(
            parent,
            "Building-block index — encoding",
            report,
            what_to_do=(
                "Re-save the index as UTF-8 CSV "
                '(Excel: "CSV UTF-8 (Comma delimited)") '
                "or upload an .xlsx index file, then Validate again."
            ),
        )
        return

    show_warning(
        parent,
        "Building-block index — mismatch",
        report,
        what_to_do=(
            "Fix missing / duplicate names in the index file so every "
            "spreadsheet building block is covered, then Validate again. "
            "Or Clear the index to use automatic alphabetical numbering."
        ),
    )


def show_bb_index_parse_errors(parent, errors: list[str] | tuple[str, ...]) -> None:
    """Dialog when an index file cannot be read or parsed."""
    detail = "\n".join(errors) if errors else "Unknown parse error."
    show_error(
        parent,
        "Building-block index",
        f"Could not read the index file:\n{detail}",
        what_to_do=(
            "Confirm the file is CSV or .xlsx with name and index columns. "
            "If names use special characters (e.g. β), save as UTF-8 or use .xlsx."
        ),
    )


def show_graphviz_missing_warning(parent, *, for_export: bool = False) -> bool:
    """
    Warn that Graphviz is missing.

    For export, asks whether to continue with the matplotlib fallback.
    Returns True when the caller should proceed (always True for non-export).
    """
    if graphviz_available():
        return True
    if for_export:
        return ask_continue(
            parent,
            "Graphviz not installed",
            graphviz_missing_export_prompt(),
        )
    show_warning(
        parent,
        "Graphviz not installed",
        graphviz_missing_banner(),
        what_to_do=(
            "Install Graphviz and ensure ``dot`` is on PATH "
            "(see dev/DEVELOPER_SETUP.md). LC-Seq will keep using the "
            "matplotlib tier-ring preview until then."
        ),
    )
    return True
