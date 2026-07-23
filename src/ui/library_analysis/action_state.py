# src/ui/library_analysis/action_state.py
"""Pure action-availability decisions for Library Analysis."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class LibraryActionInputs:
    """Facts used to decide which Library Analysis actions are available."""

    busy: bool
    has_channels: bool
    has_selected_metrics: bool
    has_selected_plots: bool
    has_scan: bool
    has_scan_cache: bool
    has_snapshot: bool
    has_latest_snapshot: bool
    has_plot_files: bool
    has_computed_metrics: bool
    has_saved_snapshots: bool
    has_report_content: bool
    rt_can_run: bool
    has_rt_result: bool
    has_pedigree: bool
    has_pedigree_tree: bool
    has_del_tree: bool
    has_splittree_plot: bool


@dataclass(frozen=True)
class LibraryActionState:
    """Widget-independent enabled states for Library Analysis actions."""

    clear_scan: bool
    calculate_metrics: bool
    generate_plots: bool
    save_snapshot: bool
    load_snapshot: bool
    browse_snapshot: bool
    export_signal_csv: bool
    export_all_plots: bool
    export_metrics_csv: bool
    clear_metrics_results: bool
    export_report: bool
    run_rt_assignment: bool
    export_pedigree: bool
    generate_pedigree_plot: bool
    export_del_tree: bool
    export_assigned_rts: bool
    export_pedigree_tree: bool
    export_splittree_png: bool
    export_splittree_branches: bool

    @classmethod
    def decide(cls, inputs: LibraryActionInputs) -> "LibraryActionState":
        """Return deterministic action states from the supplied facts."""
        available = not inputs.busy
        return cls(
            clear_scan=inputs.has_scan_cache and available,
            calculate_metrics=(
                inputs.has_channels and inputs.has_selected_metrics and available
            ),
            generate_plots=(
                inputs.has_channels and inputs.has_selected_plots and available
            ),
            save_snapshot=inputs.has_snapshot and available,
            load_snapshot=inputs.has_latest_snapshot and available,
            browse_snapshot=available,
            export_signal_csv=inputs.has_scan and inputs.has_channels and available,
            export_all_plots=inputs.has_plot_files and available,
            export_metrics_csv=inputs.has_computed_metrics and available,
            clear_metrics_results=inputs.has_saved_snapshots and available,
            export_report=inputs.has_report_content and available,
            run_rt_assignment=inputs.rt_can_run and available,
            export_pedigree=inputs.has_pedigree and available,
            generate_pedigree_plot=inputs.has_pedigree and available,
            export_del_tree=inputs.has_del_tree and available,
            export_assigned_rts=inputs.has_rt_result and available,
            export_pedigree_tree=inputs.has_pedigree and available,
            export_splittree_png=inputs.has_splittree_plot and available,
            export_splittree_branches=inputs.has_splittree_plot and available,
        )
