# src/ui/library_analysis/report_controller.py
"""Composed ReportController responsibilities for Library Analysis."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Protocol, Set, Tuple

from tkinter import filedialog, messagebox

from src.core.del_cycle_tree import DelCycleTreeData
from src.core.library_report import generate_library_report_pdf
from src.core.library_report_assets import (
    build_del_cycle_report_figures,
    session_report_assets_dir,
)
from src.core.library_report_models import (
    LibraryReportAuditTrail,
    LibraryReportOptions,
    LibraryReportPrerequisites,
    LibraryReportSectionStatus,
)
from src.core.library_report_session import (
    LibraryQcMetricsArtifact,
    LibraryQcPlotsArtifact,
    LibraryReportSession,
    PedigreeVizReportArtifact,
    RtAssignmentReportArtifact,
    SplittreeVizReportArtifact,
    build_report_snapshot,
    missing_report_sections,
)
from src.core.library_metrics import (
    DEFAULT_FRACTION_COUNT,
    LibraryComputationSnapshot,
    PlotResult,
)
from src.core.library_signal_quality import (
    DEFAULT_SIGNAL_QUALITY_ALPHA,
    SignalQualityComputeOptions,
)
from src.models.analysis_settings import AnalysisSettings
from src.models.pedigree_result import PedigreeAnalysisResult
from src.ui.library_analysis.contexts import (
    LibraryPanelContext,
    ReportControllerCallbacks,
)
from src.ui.library_analysis.models import LibraryOperationCancelled
from src.ui.library_analysis.qc_panel import QcPanel
from src.ui.library_report_dialog import LibraryReportDialogResult, show_library_report_dialog

logger = logging.getLogger(__name__)

_SPLITTREE_VIEW_BRANCH = "BB1 branch"
_SPLITTREE_RT_METADATA = "Spreadsheet metadata"


class ReportControllerContext(LibraryPanelContext, Protocol):
    """Typed host surface supplied by the composed Library Analysis window."""


class ReportController:
    """Own extracted reportcontroller behavior without importing the window."""

    def __init__(
        self,
        context: ReportControllerContext,
        qc_panel: QcPanel,
        callbacks: ReportControllerCallbacks,
    ) -> None:
        self._context = context
        self._qc_panel = qc_panel
        self._callbacks = callbacks

    def _expected_report_plot_keys(self) -> Set[Tuple[str, str]]:
        return {
            (plot_id, channel)
            for plot_id in self._qc_panel._get_selected_plot_ids()
            for channel in self._qc_panel._get_selected_channels()
        }

    def _report_session(self) -> LibraryReportSession:
        """Collect optional session artifacts available for PDF assembly."""
        assert self._context._db_path is not None
        scan = self._context._cached_scan
        return LibraryReportSession(
            database_path=str(self._context._db_path.resolve()),
            database_name=self._context._db_path.name,
            database_kind="index" if self._context._index_db_mode else "full",
            scan_entries_used=scan.entries_used if scan is not None else 0,
            scan_entries_attempted=scan.entries_attempted if scan is not None else 0,
            scan_entries_skipped=scan.entries_skipped if scan is not None else 0,
            qc_metrics=self._context._qc_metrics_artifact,
            qc_plots=self._context._qc_plots_artifact,
            rt_assignment=self._context._rt_assignment_artifact,
            pedigree_viz=self._context._pedigree_viz_artifact,
            splittree_viz=self._context._splittree_artifact,
        )

    def _session_has_report_artifacts(self) -> bool:
        return bool(self._report_session().available_section_keys())

    def _capture_qc_metrics_artifact(self, snapshot: LibraryComputationSnapshot) -> None:
        metric_ids = self._qc_panel._get_selected_metric_ids()
        channels = self._qc_panel._get_selected_channels()
        self._context._qc_metrics_artifact = LibraryQcMetricsArtifact(
            generated_at=snapshot.processed_at,
            snapshot=snapshot,
            metric_ids=list(metric_ids),
            channels=list(channels),
        )

    def _capture_qc_plots_artifact(
        self,
        plots: List[PlotResult],
        plot_ids: List[str],
    ) -> None:
        from datetime import timezone

        channels = self._qc_panel._get_selected_channels()
        self._context._qc_plots_artifact = LibraryQcPlotsArtifact(
            generated_at=datetime.now(timezone.utc),
            plot_results=list(plots),
            plot_ids=list(plot_ids),
            channels=list(channels),
        )

    def _capture_rt_assignment_artifact(
        self,
        data: DelCycleTreeData,
        *,
        analysis_mode: str,
        settings: AnalysisSettings,
        isoform: str,
    ) -> None:
        from datetime import timezone

        self._context._rt_assignment_artifact = RtAssignmentReportArtifact(
            generated_at=datetime.now(timezone.utc),
            analysis_mode=analysis_mode,
            settings=settings,
            channel=settings.count_channel,
            time_unit=str(settings.time_unit),
            isoform=isoform,
            rt_source=data.rt_source,
            rt_threshold=float(data.rt_threshold),
            n_products=len(data.verified_sequences),
            n_verified=data.n_verified,
            n_rt_from_pedigree=data.n_rt_from_pedigree,
            n_rt_from_peak_pick=data.n_rt_from_peak_pick,
            n_rt_from_metadata=data.n_rt_from_metadata,
            peak_picking_algorithm=data.peak_picking_algorithm or self._callbacks.picker_label(),
        )

    def _capture_pedigree_viz_artifact(self, result: PedigreeAnalysisResult) -> None:
        if self._context._db_path is None:
            return
        from datetime import timezone

        from src.core.library_report_assets import (
            build_pedigree_tier_report_figure,
            session_report_assets_dir,
        )

        tree_opts = self._callbacks.pedigree_render_options()
        tier_path, tier_caption = build_pedigree_tier_report_figure(
            result,
            tree_opts=tree_opts,
            output_dir=session_report_assets_dir(self._context._db_path),
        )
        self._context._pedigree_viz_artifact = PedigreeVizReportArtifact(
            generated_at=datetime.now(timezone.utc),
            image_path=tier_path,
            caption=tier_caption,
            tree_opts=tree_opts,
            n_nodes=len(result.records),
            n_chromatograms=result.n_chromatograms,
            backend_name=result.backend_name,
            tree_render_engine=result.tree_render_engine or "",
        )

    def _capture_splittree_artifact(
        self,
        data: DelCycleTreeData,
        figure: object,
        *,
        isoform: str,
        selected_branch: str,
    ) -> None:
        if self._context._db_path is None:
            return
        from datetime import timezone

        from src.core.library_report_assets import save_report_figure, session_report_assets_dir

        view_mode = self._context._splittree_view_mode_var.get()
        branch_mode = view_mode == _SPLITTREE_VIEW_BRANCH
        assets = session_report_assets_dir(self._context._db_path)
        image_path = assets / (
            f"splittree_branch_{selected_branch or 'unknown'}.png"
            if branch_mode
            else "splittree_full.png"
        )
        save_report_figure(figure, image_path)
        metadata_mode = self._context._splittree_rt_source_var.get() == _SPLITTREE_RT_METADATA
        rt_source = "metadata" if metadata_mode else "session"
        rt_column = (
            self._context._splittree_metadata_rt_column_var.get().strip() if metadata_mode else ""
        )
        caption = (
            f"Split-tree — {data.n_verified:,} verified of "
            f"{len(data.verified_sequences):,} products "
            f"(RT source: {data.rt_source}, null RT threshold {data.rt_threshold:g})."
        )
        self._context._splittree_artifact = SplittreeVizReportArtifact(
            generated_at=datetime.now(timezone.utc),
            image_path=image_path,
            caption=caption,
            rt_source=rt_source,
            rt_column=rt_column,
            isoform=isoform,
            view_mode=view_mode,
            branch_bb1=selected_branch if branch_mode else "",
            color_mode=self._callbacks.split_tree_color_mode(),
            color_by_rt=bool(self._context._pedigree_del_color_rt_var.get()),
            pass_pct_cutoff=self._callbacks.split_tree_pass_cutoff(),
            rt_threshold=float(data.rt_threshold),
            del_rt_source=data.rt_source,
            n_verified=data.n_verified,
            n_products=len(data.verified_sequences),
        )

    def _assess_report_prerequisites(
        self,
        report_options: LibraryReportOptions,
    ) -> LibraryReportPrerequisites:
        missing = missing_report_sections(report_options, self._report_session())
        return LibraryReportPrerequisites(missing_sections=missing)

    def _build_report_section_statuses(self) -> List[LibraryReportSectionStatus]:
        session = self._report_session()
        metrics = session.qc_metrics
        plots = session.qc_plots
        rt_assignment = session.rt_assignment
        pedigree_viz = session.pedigree_viz
        splittree = session.splittree_viz
        metric_ids = metrics.metric_ids if metrics is not None else []
        plot_ids = plots.plot_ids if plots is not None else []
        channels = (
            metrics.channels
            if metrics is not None
            else (plots.channels if plots is not None else [])
        )
        return [
            LibraryReportSectionStatus(
                key="metrics",
                label="Summary metrics",
                selected=metrics is not None,
                ready=metrics is not None,
                detail=(
                    f"{len(metric_ids)} metric(s) across {len(channels)} channel(s) — "
                    f"captured {self._format_report_time(metrics.generated_at)}."
                    if metrics is not None
                    else "Run Calculate metrics on the Metrics tab first."
                ),
                item_ids=list(metric_ids),
                channels=list(channels),
            ),
            LibraryReportSectionStatus(
                key="plots",
                label="Visualizations",
                selected=plots is not None,
                ready=plots is not None,
                detail=(
                    f"{len(plot_ids)} plot type(s) across {len(plots.channels)} channel(s) — "
                    f"captured {self._format_report_time(plots.generated_at)}."
                    if plots is not None
                    else "Run Generate plots on the Plots tab first."
                ),
                item_ids=list(plot_ids),
                channels=list(plots.channels) if plots is not None else [],
            ),
            LibraryReportSectionStatus(
                key="rt_assignment",
                label="RT assignment",
                selected=rt_assignment is not None,
                ready=rt_assignment is not None,
                detail=(
                    f"{rt_assignment.analysis_mode.replace('_', ' ')} mode — "
                    f"{rt_assignment.n_verified:,} verified products, "
                    f"captured {self._format_report_time(rt_assignment.generated_at)}."
                    if rt_assignment is not None
                    else "Run RT assignment on the RT assignment tab first."
                ),
            ),
            LibraryReportSectionStatus(
                key="pedigree_viz",
                label="Pedigree visualization",
                selected=pedigree_viz is not None,
                ready=pedigree_viz is not None,
                detail=(
                    f"Tier-ring — {pedigree_viz.n_nodes:,} nodes, "
                    f"captured {self._format_report_time(pedigree_viz.generated_at)}."
                    if pedigree_viz is not None
                    else "Click Generate plot on the Pedigree visualization tab first."
                ),
            ),
            LibraryReportSectionStatus(
                key="splittree",
                label="Split-tree visualization",
                selected=splittree is not None,
                ready=splittree is not None,
                detail=(
                    f"{splittree.view_mode} view ({splittree.rt_source} RT source) — "
                    f"captured {self._format_report_time(splittree.generated_at)}."
                    if splittree is not None
                    else "Click Generate plot on the Split-tree visualization tab first."
                ),
            ),
        ]

    def _build_report_audit_trail(
        self,
        report_options: LibraryReportOptions,
        session: LibraryReportSession,
    ) -> LibraryReportAuditTrail:
        assert self._context._db_path is not None
        metrics = session.qc_metrics
        rt_assignment = session.rt_assignment
        pedigree_viz = session.pedigree_viz
        splittree = session.splittree_viz
        tree_opts = (
            pedigree_viz.tree_opts
            if pedigree_viz is not None
            else self._callbacks.pedigree_render_options()
        )

        qc_opts = (
            metrics.snapshot.signal_quality_options
            if metrics is not None
            else self._qc_panel._peek_qc_signal_settings() or SignalQualityComputeOptions()
        )
        rt_settings = (
            rt_assignment.settings
            if rt_assignment is not None
            else self._callbacks.peek_pedigree_settings()
        )
        rt_min_prominence = 0.0
        rt_min_pct_area = 0.0
        if rt_settings is not None:
            rt_min_prominence, rt_min_pct_area = rt_settings.effective_quality_params()
        rt_alpha = rt_settings.alpha if rt_settings is not None else DEFAULT_SIGNAL_QUALITY_ALPHA
        rt_picker = self._callbacks.picker_label()
        if rt_assignment is not None and rt_assignment.peak_picking_algorithm:
            rt_picker = (
                "old-school Gaussian"
                if rt_assignment.peak_picking_algorithm == "old_school"
                else "modern NB"
            )
        elif rt_settings is not None:
            rt_picker = (
                "old-school Gaussian" if rt_settings.uses_old_school_peak_picker else "modern NB"
            )

        qc_min_prominence = qc_opts.min_prominence
        qc_min_pct_area = qc_opts.min_pct_area
        if qc_opts.peak_picking_algorithm == "old_school":
            qc_min_prominence = 0.0
            qc_min_pct_area = 0.0

        return LibraryReportAuditTrail(
            generated_at=datetime.now(timezone.utc),
            database_path=str(self._context._db_path.resolve()),
            database_name=self._context._db_path.name,
            database_kind="index" if self._context._index_db_mode else "full",
            report_options=report_options,
            fraction_count=(
                metrics.snapshot.fraction_count
                if metrics is not None
                else self._qc_panel._parse_fraction_count() or DEFAULT_FRACTION_COUNT
            ),
            qc_peak_picking_algorithm=qc_opts.peak_picking_algorithm,
            qc_signal_quality_alpha=qc_opts.alpha,
            qc_min_prominence=qc_min_prominence,
            qc_min_pct_area=qc_min_pct_area,
            qc_time_unit=qc_opts.time_unit,
            qc_gaussian_min_height_factor=qc_opts.gaussian_min_height_factor,
            qc_gaussian_fit_width=qc_opts.gaussian_fit_width,
            qc_gaussian_stddev_threshold=qc_opts.gaussian_stddev_threshold,
            qc_gaussian_minimum_rt=qc_opts.gaussian_minimum_rt,
            rt_min_prominence=rt_min_prominence,
            rt_min_pct_area=rt_min_pct_area,
            pedigree_channel=(
                rt_assignment.channel
                if rt_assignment is not None
                else self._context._pedigree_channel_var.get().strip()
            ),
            pedigree_time_unit=(
                rt_assignment.time_unit
                if rt_assignment is not None
                else self._context._pedigree_time_unit_var.get()
            ),
            pedigree_tolerance=(
                rt_assignment.rt_threshold
                if rt_assignment is not None
                else float(self._context._pedigree_tolerance_var.get().strip() or "0")
            ),
            pedigree_alpha=rt_alpha,
            pedigree_peak_picker=rt_picker,
            rt_gaussian_min_height_factor=(
                rt_settings.gaussian_min_height_factor if rt_settings is not None else 0.35
            ),
            rt_gaussian_fit_width=(
                rt_settings.gaussian_fit_width if rt_settings is not None else 30.0
            ),
            rt_gaussian_stddev_threshold=(
                rt_settings.gaussian_stddev_threshold if rt_settings is not None else 2.0
            ),
            rt_gaussian_minimum_rt=(
                rt_settings.gaussian_minimum_rt if rt_settings is not None else 600.0
            ),
            pedigree_isoform=rt_assignment.isoform if rt_assignment is not None else "All",
            pedigree_max_display_tier=tree_opts.max_display_tier,
            pedigree_include_failed=tree_opts.include_failed,
            pedigree_show_rt=tree_opts.show_rt,
            rt_analysis_mode=rt_assignment.analysis_mode if rt_assignment is not None else "",
            splittree_rt_source=splittree.rt_source if splittree is not None else "",
            splittree_rt_column=splittree.rt_column if splittree is not None else "",
            splittree_isoform=splittree.isoform if splittree is not None else "All",
            splittree_view_mode=splittree.view_mode if splittree is not None else "",
            del_color_mode=(
                splittree.color_mode
                if splittree is not None
                else self._callbacks.split_tree_color_mode()
            ),
            del_color_by_rt=(
                splittree.color_by_rt
                if splittree is not None
                else bool(self._context._pedigree_del_color_rt_var.get())
            ),
            del_rt_threshold=splittree.rt_threshold if splittree is not None else 0.0,
            del_rt_source=splittree.del_rt_source if splittree is not None else "",
        )

    def _confirm_report_export(
        self,
        pdf_path: Path,
        report_options: LibraryReportOptions,
    ) -> bool:
        sections = []
        if report_options.include_metrics:
            sections.append(f"Summary metrics ({len(report_options.metric_ids)})")
        if report_options.include_plots:
            sections.append(f"Visualizations ({len(report_options.plot_ids)})")
        if report_options.include_rt_assignment:
            sections.append("RT assignment")
        if report_options.include_pedigree_viz:
            sections.append("Pedigree visualization")
        if report_options.include_splittree:
            sections.append("Split-tree visualization")
        return self._context._confirm_long_operation(
            "\n".join(
                [
                    f"Save library report to:\n{pdf_path}\n",
                    "Sections: " + ", ".join(sections),
                    "\nThe PDF will embed session artifacts you already generated. Continue?",
                ]
            )
        )

    def _on_export_report(self) -> None:
        if self._context._is_busy():
            return
        if (
            self._context._data_store is not None
            and self._context._data_store.get_compound_count() == 0
        ):
            messagebox.showinfo(
                "Library Analysis",
                "The database has no compounds to report on.",
                parent=self._context,
            )
            return
        if not self._session_has_report_artifacts():
            messagebox.showinfo(
                "Generate report",
                "No report sections are ready yet.\n\n"
                "Run metrics, plots, RT assignment, or split-tree steps "
                "in this session, then return here to assemble a PDF.",
                parent=self._context,
            )
            return

        session = self._report_session()
        default_options = LibraryReportOptions(
            include_metrics=session.qc_metrics is not None,
            include_plots=session.qc_plots is not None,
            include_rt_assignment=session.rt_assignment is not None,
            include_pedigree_viz=session.pedigree_viz is not None,
            include_splittree=session.splittree_viz is not None,
            metric_ids=list(session.qc_metrics.metric_ids) if session.qc_metrics else [],
            plot_ids=list(session.qc_plots.plot_ids) if session.qc_plots else [],
            channels=list(
                dict.fromkeys(
                    [
                        *(session.qc_metrics.channels if session.qc_metrics else []),
                        *(session.qc_plots.channels if session.qc_plots else []),
                    ]
                )
            ),
        )
        prerequisites = self._assess_report_prerequisites(default_options)
        section_statuses = self._build_report_section_statuses()

        def on_dialog_confirm(result: LibraryReportDialogResult) -> None:
            self._continue_report_export(result)

        show_library_report_dialog(
            self._context,
            section_statuses=section_statuses,
            prerequisites=prerequisites,
            on_confirm=on_dialog_confirm,
            reassess=self._assess_report_prerequisites,
        )

    def _continue_report_export(self, dialog_result: LibraryReportDialogResult) -> None:
        report_options = dialog_result.options
        prerequisites = self._assess_report_prerequisites(report_options)
        if prerequisites.missing_sections:
            messagebox.showinfo(
                "Generate report",
                "Some selected sections are not available yet:\n\n"
                + "\n".join(f"• {note}" for note in prerequisites.missing_sections),
                parent=self._context,
            )
            return

        dest = filedialog.asksaveasfilename(
            parent=self._context,
            title="Export library report",
            defaultextension=".pdf",
            filetypes=[("PDF document", "*.pdf")],
        )
        if not dest:
            return
        pdf_path = Path(dest)
        if not self._confirm_report_export(pdf_path, report_options):
            return
        self._start_report_export(pdf_path, report_options)

    def _start_report_export(
        self,
        pdf_path: Path,
        report_options: LibraryReportOptions,
    ) -> None:
        assert self._context._db_path is not None
        session = self._report_session()
        audit = self._build_report_audit_trail(report_options, session)
        snapshot = build_report_snapshot(session)
        plot_results = (
            list(session.qc_plots.plot_results)
            if report_options.include_plots and session.qc_plots is not None
            else []
        )
        rt_assignment = session.rt_assignment if report_options.include_rt_assignment else None
        pedigree_viz = session.pedigree_viz if report_options.include_pedigree_viz else None
        splittree_viz = session.splittree_viz if report_options.include_splittree else None
        del_data = (
            self._context._splittree_viz_data or self._context._del_cycle_tree_data
            if report_options.include_splittree
            else None
        )
        db_path = self._context._db_path
        splittree_color_mode = (
            splittree_viz.color_mode
            if splittree_viz is not None
            else self._callbacks.split_tree_color_mode()
        )
        splittree_color_by_rt = (
            splittree_viz.color_by_rt
            if splittree_viz is not None
            else bool(self._context._pedigree_del_color_rt_var.get())
        )
        splittree_pass_pct = (
            splittree_viz.pass_pct_cutoff
            if splittree_viz is not None
            else self._callbacks.split_tree_pass_cutoff()
        )
        splittree_shows_full = (
            splittree_viz.view_mode.strip().lower() in ("full tree", "full")
            if splittree_viz is not None
            else True
        )

        self._context._show_loading_page("Exporting library report", "Writing PDF…")
        self._context._update_action_states()

        def worker() -> None:
            try:
                self._context._thread_loading_progress(
                    0.35, "Rendering split-tree figures for report…"
                )
                pedigree_figures = None
                if del_data is not None and report_options.include_splittree:
                    assets_dir = session_report_assets_dir(db_path) / "split_tree_report"
                    pedigree_figures = build_del_cycle_report_figures(
                        del_data,
                        del_color_mode=splittree_color_mode,
                        del_color_by_rt=splittree_color_by_rt,
                        del_pass_pct_cutoff=splittree_pass_pct,
                        output_dir=assets_dir,
                        include_full_tree=not splittree_shows_full,
                    )
                self._context._thread_loading_progress(0.65, "Writing PDF report…")
                generate_library_report_pdf(
                    snapshot,
                    pdf_path,
                    plot_results=plot_results,
                    report_options=report_options,
                    audit=audit,
                    rt_assignment=rt_assignment,
                    pedigree_viz=pedigree_viz,
                    splittree_viz=splittree_viz,
                    pedigree_figures=pedigree_figures,
                )
                self._context._bind_worker_callback(
                    self._on_report_export_ready,
                    str(pdf_path.resolve()),
                )
            except LibraryOperationCancelled:
                raise
            except Exception as exc:
                logger.error("Library report export failed: %s", exc, exc_info=True)
                self._context._bind_worker_callback(self._context._on_worker_error, str(exc))

        self._context._start_worker(worker)

    def _on_report_export_ready(self, pdf_path: str) -> None:
        if not self._context._ui_is_active():
            return
        self._context._worker_thread = None
        self._context._update_loading_progress(1.0, f"Report saved: {pdf_path}")

        def finish() -> None:
            if not self._context._ui_is_active():
                return
            self._context._hide_loading_page()
            self._context._update_action_states()
            messagebox.showinfo(
                "Library Analysis",
                f"Library report saved to:\n{pdf_path}",
                parent=self._context,
            )

        self._context.after(30, finish)

    @staticmethod
    def _format_report_time(when: datetime) -> str:
        if when.tzinfo is None:
            return when.strftime("%Y-%m-%d %H:%M")
        return when.astimezone().strftime("%Y-%m-%d %H:%M")
