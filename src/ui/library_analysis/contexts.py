# src/ui/library_analysis/contexts.py
"""Explicit cross-component capabilities for Library Analysis panels."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List, Optional, Protocol

from src.core.data_store import DataStore
from src.core.del_cycle_tree import DelCycleTreeData
from src.core.library_metrics import (
    LibraryComputationSnapshot,
    LibraryScanData,
    PlotResult,
)
from src.core.pedigree_render import PedigreeTreeRenderOptions
from src.models.analysis_settings import AnalysisSettings
from src.models.pedigree_result import PedigreeAnalysisResult
from src.models.spreadsheet_config import SpreadsheetConfig


@dataclass(frozen=True)
class QcPanelCallbacks:
    """Cross-component publications emitted by the QC panel."""

    capture_metrics: Callable[[LibraryComputationSnapshot], None]
    capture_plots: Callable[[List[PlotResult], List[str]], None]


@dataclass(frozen=True)
class ReportControllerCallbacks:
    """Analysis settings queried while composing a report."""

    picker_label: Callable[[], str]
    pedigree_render_options: Callable[[], PedigreeTreeRenderOptions]
    split_tree_color_mode: Callable[[], str]
    split_tree_pass_cutoff: Callable[[], float]
    peek_pedigree_settings: Callable[[], Optional[AnalysisSettings]]


@dataclass(frozen=True)
class RtAssignmentCallbacks:
    """Pedigree, split-tree, and report actions used by RT assignment."""

    run_pedigree: Callable[[], None]
    split_tree_color_mode: Callable[[], str]
    split_tree_pass_cutoff: Callable[[], float]
    sorted_branch_names: Callable[[DelCycleTreeData], List[str]]
    resolve_branch: Callable[[DelCycleTreeData, str], Optional[str]]
    update_branch_choices: Callable[[DelCycleTreeData], None]
    update_tree_status: Callable[[DelCycleTreeData], None]
    capture_rt_artifact: Callable[..., None]
    mount_split_tree: Callable[[object], None]
    show_split_tree_placeholder: Callable[[str], None]
    render_cached_split_tree: Callable[[str, bool], None]


@dataclass(frozen=True)
class PedigreePanelCallbacks:
    """RT, report, and split-tree actions used by pedigree analysis."""

    parse_settings: Callable[[], Optional[AnalysisSettings]]
    update_rt_results: Callable[..., None]
    capture_visualization: Callable[[PedigreeAnalysisResult], None]
    update_split_tree_status: Callable[[], None]
    ensure_del_cycle_tree: Callable[[], None]


@dataclass(frozen=True)
class SplitTreePanelCallbacks:
    """RT-assignment status queried and refreshed by split-tree analysis."""

    session_rt_ready: Callable[[], bool]
    update_rt_status: Callable[[], None]
    ensure_session_tree: Callable[[], None]
    parse_settings: Callable[[], Optional[AnalysisSettings]]
    peek_settings: Callable[[], Optional[AnalysisSettings]]
    capture_visualization: Callable[[DelCycleTreeData, object, str, str], None]


class LibraryPanelContext(Protocol):
    """Shared lifecycle, task, navigation, and result capabilities."""

    _db_path: Optional[Path]
    _data_store: Optional[DataStore]
    _config: Optional[SpreadsheetConfig]
    _index_db_mode: bool

    @property
    def _cached_scan(self) -> Optional[LibraryScanData]:
        """Return the active parsed scan."""
        ...

    @_cached_scan.setter
    def _cached_scan(self, value: Optional[LibraryScanData]) -> None: ...

    @property
    def _current_snapshot(self) -> Optional[LibraryComputationSnapshot]:
        """Return the active QC snapshot."""
        ...

    @property
    def _pedigree_result(self) -> Optional[PedigreeAnalysisResult]:
        """Return the active pedigree result."""
        ...

    @_pedigree_result.setter
    def _pedigree_result(self, value: Optional[PedigreeAnalysisResult]) -> None: ...

    @property
    def _del_cycle_tree_data(self) -> Optional[DelCycleTreeData]:
        """Return the active RT-assignment tree data."""
        ...

    @_del_cycle_tree_data.setter
    def _del_cycle_tree_data(self, value: Optional[DelCycleTreeData]) -> None: ...

    @property
    def _splittree_viz_data(self) -> Optional[DelCycleTreeData]:
        """Return the active split-tree result."""
        ...

    @_splittree_viz_data.setter
    def _splittree_viz_data(self, value: Optional[DelCycleTreeData]) -> None: ...

    def _ui_is_active(self) -> bool:
        """Return whether callbacks may still update the window."""
        ...

    def _dispatch_to_tk(self, callback: Callable[[], None]) -> None:
        """Queue a callback on Tk's event loop."""
        ...

    def _schedule_on_main(
        self,
        callback: Callable[..., None],
        *args: object,
    ) -> None:
        """Schedule a lifecycle callback on Tk's event loop."""
        ...

    def _bind_worker_callback(
        self,
        callback: Callable[..., None],
        *args: object,
    ) -> None:
        """Schedule the current operation's terminal callback."""
        ...

    def _start_worker(self, worker: Callable[[], None]) -> None:
        """Start one coordinated background operation."""
        ...

    def _thread_loading_progress(self, fraction: float, status: str) -> None:
        """Publish operation progress."""
        ...

    def _raise_if_cancelled(self) -> None:
        """Raise when cancellation was requested."""
        ...

    def _is_busy(self) -> bool:
        """Return whether an operation is active."""
        ...

    def _show_loading_page(self, title: str, detail: str = "") -> None:
        """Show operation progress."""
        ...

    def _hide_loading_page(self, *, clear_cancel: bool = True) -> None:
        """Restore normal content after an operation."""
        ...

    def _update_action_states(self) -> None:
        """Apply current action availability to widgets."""
        ...

    def _focus_tab(self, tab_name: str) -> None:
        """Select a result tab and its paired sidebar."""
        ...
