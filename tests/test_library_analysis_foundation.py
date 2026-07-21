# tests/test_library_analysis_foundation.py
"""Headless tests for Library Analysis state and task coordination."""

from __future__ import annotations

import threading
from typing import Any, Callable, List, Tuple, cast

from src.ui.library_analysis.state import LibraryAnalysisState
from src.ui.library_analysis.task_coordinator import TaskCoordinator


def _pop_all(callbacks: List[Callable[[], None]]) -> None:
    """Run every callback queued by the test dispatcher."""
    while callbacks:
        callbacks.pop(0)()


def test_scan_invalidation_clears_all_dependent_results() -> None:
    state = LibraryAnalysisState()
    marker = cast(Any, object())
    state.scan = marker
    state.snapshot = marker
    state.snapshot_path = marker
    state.plots = [marker]
    state.qc_metrics_artifact = marker
    state.qc_plots_artifact = marker
    state.rt_assignment_artifact = marker
    state.pedigree_viz_artifact = marker
    state.splittree_viz_artifact = marker
    state.pedigree_result = marker
    state.pedigree_snapshot_path = marker
    state.rt_assignment_result = marker
    state.splittree_result = marker

    state.invalidate_scan()

    assert state.scan is None
    assert state.snapshot is None
    assert state.snapshot_path is None
    assert state.plots == []
    assert state.qc_metrics_artifact is None
    assert state.qc_plots_artifact is None
    assert state.rt_assignment_artifact is None
    assert state.pedigree_viz_artifact is None
    assert state.splittree_viz_artifact is None
    assert state.pedigree_result is None
    assert state.pedigree_snapshot_path is None
    assert state.rt_assignment_result is None
    assert state.splittree_result is None


def test_cancelled_operation_rejects_already_queued_result() -> None:
    callbacks: List[Callable[[], None]] = []
    queued = threading.Event()
    accepted: List[str] = []
    coordinator = TaskCoordinator(callbacks.append, lambda: True)

    def worker() -> None:
        coordinator.dispatch_current(accepted.append, "stale", complete=True)
        queued.set()

    operation = coordinator.start(worker)
    assert queued.wait(timeout=2)

    cancelled = coordinator.cancel_active()
    _pop_all(callbacks)

    assert cancelled is operation
    assert operation.is_cancelled
    assert accepted == []
    assert not coordinator.is_busy


def test_superseded_operation_cannot_publish_into_new_operation() -> None:
    callbacks: List[Callable[[], None]] = []
    first_queued = threading.Event()
    second_queued = threading.Event()
    accepted: List[Tuple[str, bool]] = []
    coordinator = TaskCoordinator(callbacks.append, lambda: True)

    def accept(name: str) -> None:
        accepted.append((name, coordinator.is_busy))

    def first_worker() -> None:
        coordinator.dispatch_current(accept, "first", complete=True)
        first_queued.set()

    def second_worker() -> None:
        coordinator.dispatch_current(accept, "second", complete=True)
        second_queued.set()

    coordinator.start(first_worker)
    assert first_queued.wait(timeout=2)
    coordinator.cancel_active()
    coordinator.start(second_worker)
    assert second_queued.wait(timeout=2)

    _pop_all(callbacks)

    assert accepted == [("second", False)]
    assert not coordinator.is_busy
