# tests/test_library_analysis_splittree_composition.py
"""Headless tests for composed split-tree source and status decisions."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from src.core.del_cycle_tree.models import MetadataRtColumnInfo
from src.ui.library_analysis.splittree_panel import (
    SPLITTREE_RT_METADATA,
    SPLITTREE_RT_SESSION,
    SplitTreePanel,
    _MetadataValidationSelection,
)


class _Value:
    """Minimal Tk-variable substitute for panel decision tests."""

    def __init__(self, value: Any) -> None:
        self._value = value

    def get(self) -> Any:
        """Return the stored value."""
        return self._value


def _panel(source: str) -> SplitTreePanel:
    """Create a panel with only headless coordination capabilities."""
    context = SimpleNamespace(
        _dispatch_to_tk=lambda callback: callback(),
        _ui_is_active=lambda: True,
        _is_busy=lambda: False,
        _splittree_rt_source_var=_Value(source),
    )
    callbacks = SimpleNamespace(
        session_rt_ready=lambda: False,
        update_rt_status=lambda: None,
    )
    return SplitTreePanel(context, callbacks)


def test_generate_dispatches_to_metadata_source() -> None:
    panel = _panel(SPLITTREE_RT_METADATA)
    calls: list[str] = []
    panel._metadata_selection_is_validated = lambda: True  # type: ignore[method-assign]
    panel._generate_splittree_from_metadata = lambda: calls.append("metadata")  # type: ignore[method-assign]
    panel._generate_splittree_from_session = lambda: calls.append("session")  # type: ignore[method-assign]

    panel._on_generate_splittree_plot()

    assert calls == ["metadata"]


def test_generate_blocks_unvalidated_metadata_selection(monkeypatch) -> None:
    panel = _panel(SPLITTREE_RT_METADATA)
    calls: list[str] = []
    notices: list[str] = []
    panel._metadata_selection_is_validated = lambda: False  # type: ignore[method-assign]
    panel._generate_splittree_from_metadata = lambda: calls.append("metadata")  # type: ignore[method-assign]
    monkeypatch.setattr(
        "src.ui.library_analysis.splittree_panel.messagebox.showinfo",
        lambda _title, message, **_kwargs: notices.append(message),
    )

    panel._on_generate_splittree_plot()

    assert calls == []
    assert notices
    assert "Validate the selected spreadsheet RT column" in notices[0]


def test_generate_reuses_session_before_rebuilding() -> None:
    panel = _panel(SPLITTREE_RT_SESSION)
    calls: list[str] = []
    panel._reuse_session_del_cycle_for_splittree = lambda: True  # type: ignore[method-assign]
    panel._generate_splittree_from_session = lambda: calls.append("session")  # type: ignore[method-assign]

    panel._on_generate_splittree_plot()

    assert calls == []


def test_rt_status_reports_selected_column_coverage() -> None:
    discovered = [
        MetadataRtColumnInfo(
            column_name="Assigned RT",
            n_numeric_values=75,
            n_compounds_scanned=100,
            n_with_bb_positions=70,
        )
    ]

    status = SplitTreePanel._format_splittree_rt_column_status(
        discovered,
        selected="Assigned RT",
    )

    assert status == (
        "“Assigned RT”: 75 numeric values (75.0% of library), " "70 with BB positions."
    )


def test_metadata_validation_accepts_numeric_rt_column_with_bb_positions() -> None:
    """The selected RT column must contain numeric values on usable library rows."""
    selection = _MetadataValidationSelection(
        rt_column="Assigned RT",
        isoform="All",
    )
    validated = [
        MetadataRtColumnInfo(
            column_name="Assigned RT",
            n_numeric_values=12,
            n_compounds_scanned=20,
            n_with_bb_positions=10,
        ),
    ]

    assert SplitTreePanel._metadata_validation_error(selection, validated) is None


def test_metadata_validation_rejects_rt_column_without_usable_rows() -> None:
    """Numeric values must occur on rows with configured BB positions."""
    selection = _MetadataValidationSelection(
        rt_column="Assigned RT",
        isoform="All",
    )
    validated = [
        MetadataRtColumnInfo(
            column_name="Assigned RT",
            n_numeric_values=12,
            n_compounds_scanned=20,
            n_with_bb_positions=0,
        ),
    ]

    error = SplitTreePanel._metadata_validation_error(selection, validated)

    assert error is not None
    assert "BB positions" in error
