# tests/test_library_analysis_qc_report_composition.py
"""Headless tests for composed QC and report responsibilities."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

from src.ui.library_analysis.qc_panel import QcPanel
from src.ui.library_analysis.report_controller import ReportController


def _empty_report_context(database_path: Path) -> Any:
    """Build the minimal typed-context substitute needed by report session tests."""
    return SimpleNamespace(
        _db_path=database_path,
        _index_db_mode=False,
        _cached_scan=None,
        _qc_metrics_artifact=None,
        _qc_plots_artifact=None,
        _rt_assignment_artifact=None,
        _pedigree_viz_artifact=None,
        _splittree_artifact=None,
    )


def test_report_controller_builds_empty_session_and_readiness(tmp_path: Path) -> None:
    database_path = tmp_path / "library.db"
    controller = ReportController(
        cast(Any, _empty_report_context(database_path)),
        cast(Any, SimpleNamespace()),
        cast(Any, SimpleNamespace()),
    )

    session = controller._report_session()
    statuses = controller._build_report_section_statuses()

    assert session.database_path == str(database_path.resolve())
    assert session.database_name == "library.db"
    assert session.database_kind == "full"
    assert session.available_section_keys() == []
    assert [status.key for status in statuses] == [
        "metrics",
        "plots",
        "rt_assignment",
        "pedigree_viz",
        "splittree",
    ]
    assert all(not status.ready for status in statuses)


def test_qc_panel_scan_entry_count_prefers_entries_used() -> None:
    panel = QcPanel(
        cast(Any, SimpleNamespace()),
        cast(Any, SimpleNamespace()),
    )
    scan = SimpleNamespace(entries_used=17, entries=[object()] * 25)

    assert panel._scan_entry_count(cast(Any, scan)) == 17


def test_background_scan_restore_does_not_replace_newer_scan() -> None:
    """A completed startup restore must not overwrite newer in-memory work."""
    existing_scan = SimpleNamespace(entries_used=3, entries=[object()] * 3)
    restored_scan = SimpleNamespace(entries_used=8, entries=[object()] * 8)
    context = SimpleNamespace(
        _cached_scan=existing_scan,
        _is_busy=lambda: False,
    )
    panel = QcPanel(cast(Any, context), cast(Any, SimpleNamespace()))
    applied: list[Any] = []
    panel._apply_loaded_scan = (  # type: ignore[method-assign]
        lambda scan, **_kwargs: applied.append(scan)
    )

    panel._accept_restored_session_scan(cast(Any, restored_scan))

    assert applied == []


def test_background_scan_restore_applies_when_window_is_idle() -> None:
    restored_scan = SimpleNamespace(entries_used=8, entries=[object()] * 8)
    context = SimpleNamespace(
        _cached_scan=None,
        _is_busy=lambda: False,
    )
    panel = QcPanel(cast(Any, context), cast(Any, SimpleNamespace()))
    applied: list[tuple[Any, dict[str, Any]]] = []
    panel._apply_loaded_scan = (  # type: ignore[method-assign]
        lambda scan, **kwargs: applied.append((scan, kwargs))
    )

    panel._accept_restored_session_scan(cast(Any, restored_scan))

    assert applied == [(restored_scan, {"persist": False})]


def test_composed_modules_do_not_import_window_class() -> None:
    module_dir = Path(__file__).parents[1] / "src" / "ui" / "library_analysis"

    for filename in ("qc_panel.py", "report_controller.py"):
        source = (module_dir / filename).read_text(encoding="utf-8")
        assert "LibraryDataWindow" not in source
