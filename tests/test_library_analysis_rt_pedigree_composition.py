# tests/test_library_analysis_rt_pedigree_composition.py
"""Headless tests for composed RT-assignment and pedigree panels."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from src.ui.library_analysis.pedigree_panel import PedigreePanel
from src.ui.library_analysis.contexts import PedigreePanelCallbacks
from src.ui.library_analysis.rt_assignment_panel import RtAssignmentPanel


class _Value:
    """Minimal Tk-variable substitute for headless panel tests."""

    def __init__(self, value: Any) -> None:
        self._value = value

    def get(self) -> Any:
        """Return the stored value."""
        return self._value

    def set(self, value: Any) -> None:
        """Replace the stored value."""
        self._value = value


class _SessionState:
    """Record split-tree invalidation without constructing Tk."""

    def __init__(self) -> None:
        self.invalidated = False

    def invalidate_splittree(self) -> None:
        """Record the requested invalidation."""
        self.invalidated = True


def test_rt_mode_dispatch_preserves_direct_and_pedigree_paths() -> None:
    session = _SessionState()
    calls: list[str] = []
    host = SimpleNamespace(
        _session_state=session,
        _rt_analysis_mode_var=_Value("direct_pick"),
        _last_rt_analysis_mode=None,
        _rt_assignment_artifact=object(),
        _pedigree_viz_artifact=object(),
        _on_run_pedigree=lambda: calls.append("pedigree"),
    )
    panel = RtAssignmentPanel(
        host,
        SimpleNamespace(),
        SimpleNamespace(run_pedigree=lambda: calls.append("pedigree")),
    )
    panel._on_run_direct_pick_assignment = lambda: calls.append("direct")  # type: ignore[method-assign]

    panel._on_run_rt_assignment()
    host._rt_analysis_mode_var.set("pedigree")
    panel._on_run_rt_assignment()

    assert calls == ["direct", "pedigree"]
    assert session.invalidated
    assert host._last_rt_analysis_mode == "pedigree"
    assert host._rt_assignment_artifact is None
    assert host._pedigree_viz_artifact is None


def test_rt_settings_remain_siloed_from_qc_picker_settings() -> None:
    host = SimpleNamespace(
        _config=SimpleNamespace(analysis_time_unit="seconds"),
        _pedigree_channel_var=_Value("Count A"),
        _pedigree_time_unit_var=_Value("minutes"),
        _pedigree_tolerance_var=_Value("0.5"),
        _pedigree_alpha_var=_Value("0.002"),
        _pedigree_min_prominence_var=_Value("7"),
        _pedigree_min_pct_area_var=_Value("4"),
        _pedigree_picker_algorithm_var=_Value("old_school"),
        _pedigree_gaussian_height_var=_Value("0.4"),
        _pedigree_gaussian_fit_width_var=_Value("12"),
        _pedigree_gaussian_stddev_var=_Value("1.8"),
        _pedigree_gaussian_min_rt_var=_Value("6"),
    )

    settings = RtAssignmentPanel(
        host,
        SimpleNamespace(),
        SimpleNamespace(),
    )._peek_pedigree_settings()

    assert settings is not None
    assert settings.count_channel == "Count A"
    assert settings.time_unit == "minutes"
    assert settings.chromatogram_time_unit == "seconds"
    assert settings.peak_picking_algorithm == "old_school"
    assert settings.gaussian_fit_width == 12.0


def test_pedigree_render_options_are_composed_from_tier_controls() -> None:
    host = SimpleNamespace(
        _pedigree_tree_tier_slider=_Value(3.0),
        _pedigree_include_failed_var=_Value(False),
        _pedigree_show_rt_var=_Value(True),
    )

    options = PedigreePanel(
        host,
        SimpleNamespace(),
        SimpleNamespace(),
    )._pedigree_tree_render_options()

    assert options.max_display_tier == 3
    assert options.include_failed is False
    assert options.show_rt is True


def test_pedigree_ready_defers_visualization_until_generate() -> None:
    """Completing RT assignment must leave plot generation as an explicit action."""
    captured: list[object] = []
    placeholders: list[str] = []
    selected_tab = _Value("")
    host = SimpleNamespace(
        _worker_thread=object(),
        _pedigree_result=None,
        _pedigree_snapshot_path=object(),
        _pedigree_viz_artifact=object(),
        _pedigree_status_label=None,
        _content_tabview=selected_tab,
        _hide_loading_page=lambda: None,
        _update_action_states=lambda: None,
        _schedule_on_main=lambda callback: None,
    )
    callbacks = PedigreePanelCallbacks(
        parse_settings=lambda: None,
        update_rt_results=lambda **kwargs: None,
        capture_visualization=lambda result: captured.append(result),
        update_split_tree_status=lambda: None,
        ensure_del_cycle_tree=lambda: None,
        update_branch_choices=lambda data: None,
    )
    panel = PedigreePanel(host, SimpleNamespace(), callbacks)
    panel._update_pedigree_graphviz_banner = lambda: None  # type: ignore[method-assign]
    panel._display_pedigree_result = lambda result: None  # type: ignore[method-assign]
    panel._show_pedigree_tree_placeholder = placeholders.append  # type: ignore[method-assign]
    result = SimpleNamespace(records=[], n_chromatograms=0)

    panel._on_pedigree_ready(result)

    assert host._pedigree_result is result
    assert host._pedigree_viz_artifact is None
    assert selected_tab.get() == "RT assignment"
    assert captured == []
    assert placeholders == ["Pedigree RT assignment ready. Click Generate plot in the sidebar."]
