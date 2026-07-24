# src/ui/library_analysis/pedigree_panel.py
"""Composed pedigree visualization responsibilities for Library Analysis."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import List, Optional, Protocol

import customtkinter as ctk
from tkinter import filedialog, messagebox

from src.core.pedigree_analysis_store import session_pedigree_dir
from src.core.pedigree_backend import pedigree_backend_available
from src.core.pedigree_export import export_pedigree_csv
from src.core.pedigree_render import (
    PedigreeTreeRenderOptions,
    build_default_tree_render_options,
    build_pedigree_tree_matplotlib_figure,
    build_pedigree_tree_preview_figure,
    count_visible_pedigree_nodes,
    graphviz_available,
    graphviz_install_hint,
    max_tier_in_records,
    render_pedigree_tree,
    suggest_include_failed,
)
from src.core.pedigree_service import run_pedigree_analysis_for_path
from src.models.analysis_settings import AnalysisSettings
from src.models.pedigree_result import PedigreeAnalysisResult, PedigreeTierSummary
from src.ui.library_analysis.contexts import (
    LibraryPanelContext,
    PedigreePanelCallbacks,
)
from src.ui.library_analysis.models import LibraryOperationCancelled
from src.ui.library_analysis.qc_panel import QcPanel
from src.ui.ui_messages import show_error, show_graphviz_missing_warning, show_info

logger = logging.getLogger(__name__)

_TAB_RT_ASSIGNMENT = "RT assignment"
_SIDEBAR_WRAP = 280


class PedigreePanelContext(LibraryPanelContext, Protocol):
    """Typed host surface supplied through composition."""


class PedigreePanel:
    """Own composed pedigree visualization behavior without importing the host window."""

    def __init__(
        self,
        context: PedigreePanelContext,
        qc_panel: QcPanel,
        callbacks: PedigreePanelCallbacks,
    ) -> None:
        self._context = context
        self._qc_panel = qc_panel
        self._callbacks = callbacks

    def _build_pedigree_viz_sidebar_content(self, panel: ctk.CTkScrollableFrame) -> None:
        """Build pedigree display controls, action, and tier summary."""
        ctk.CTkLabel(
            panel,
            text="Pedigree tree display",
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color=("#0969da", "#58a6ff"),
            anchor="w",
        ).grid(row=0, column=0, sticky="ew", padx=8, pady=(8, 4))
        self._context._pedigree_generate_btn = ctk.CTkButton(
            panel,
            text="Generate plot",
            font=ctk.CTkFont(size=14, weight="bold"),
            height=36,
            fg_color="#1F6FEB",
            command=self._on_generate_pedigree_plot,
            state="disabled",
        )
        self._context._pedigree_generate_btn.grid(row=1, column=0, sticky="ew", padx=8, pady=(0, 8))
        controls = ctk.CTkFrame(panel, corner_radius=8)
        controls.grid(row=2, column=0, sticky="ew", padx=8, pady=(0, 12))
        controls.grid_columnconfigure(0, weight=1)
        self._build_pedigree_display_controls(controls)

        ctk.CTkLabel(
            panel,
            text="Tier summary",
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color=("#0969da", "#58a6ff"),
            anchor="w",
        ).grid(row=3, column=0, sticky="ew", padx=8, pady=(0, 4))
        self._context._pedigree_frame = ctk.CTkFrame(panel, fg_color="transparent")
        self._context._pedigree_frame.grid(row=4, column=0, sticky="ew", padx=8, pady=(0, 8))
        self._context._pedigree_frame.grid_columnconfigure(0, weight=1)

    def _build_pedigree_display_controls(self, parent: ctk.CTkFrame) -> None:
        """Build display controls inside the pedigree visualization sidebar."""
        self._context._pedigree_graphviz_banner = ctk.CTkLabel(
            parent,
            text="",
            font=ctk.CTkFont(size=10),
            text_color="#B8860B",
            anchor="w",
            wraplength=_SIDEBAR_WRAP,
            justify="left",
        )
        self._context._pedigree_graphviz_banner.grid(
            row=0, column=0, sticky="ew", padx=8, pady=(8, 4)
        )
        self._update_pedigree_graphviz_banner()

        self._context._pedigree_tier_controls_frame = ctk.CTkFrame(parent, fg_color="transparent")
        self._context._pedigree_tier_controls_frame.grid(row=1, column=0, sticky="ew")
        self._context._pedigree_tier_controls_frame.grid_columnconfigure(0, weight=1)
        ctk.CTkCheckBox(
            self._context._pedigree_tier_controls_frame,
            text="Show failed trim points",
            variable=self._context._pedigree_include_failed_var,
            command=self._on_pedigree_tree_option_changed,
        ).grid(row=0, column=0, sticky="w", padx=8, pady=2)
        ctk.CTkCheckBox(
            self._context._pedigree_tier_controls_frame,
            text="Show chosen RT on passed nodes",
            variable=self._context._pedigree_show_rt_var,
            command=self._on_pedigree_tree_option_changed,
        ).grid(row=1, column=0, sticky="w", padx=8, pady=2)

        tier_row = ctk.CTkFrame(
            self._context._pedigree_tier_controls_frame,
            fg_color="transparent",
        )
        tier_row.grid(row=2, column=0, sticky="ew", padx=8, pady=(4, 2))
        tier_row.grid_columnconfigure(0, weight=1)
        self._context._pedigree_tree_tier_label = ctk.CTkLabel(
            tier_row,
            text="Max tier shown: —",
            font=ctk.CTkFont(size=11),
            anchor="w",
        )
        self._context._pedigree_tree_tier_label.grid(row=0, column=0, sticky="w")
        max_tier_default = max(
            0,
            (self._context._config.library_cycle_count or 1) - 1,
        )
        self._context._pedigree_tree_tier_slider = ctk.CTkSlider(
            tier_row,
            from_=0,
            to=max(max_tier_default, 1),
            number_of_steps=max(max_tier_default, 1),
            command=self._on_pedigree_tier_slider_changed,
        )
        self._context._pedigree_tree_tier_slider.set(float(max_tier_default))
        self._context._pedigree_tree_tier_slider.grid(row=1, column=0, sticky="ew", pady=(2, 0))
        self._context._pedigree_tree_dense_note = ctk.CTkLabel(
            parent,
            text="",
            font=ctk.CTkFont(size=10),
            text_color="gray",
            anchor="w",
            wraplength=_SIDEBAR_WRAP,
            justify="left",
        )
        self._context._pedigree_tree_dense_note.grid(
            row=2, column=0, sticky="ew", padx=8, pady=(2, 0)
        )
        self._context._pedigree_tree_node_count_label = ctk.CTkLabel(
            parent,
            text="",
            font=ctk.CTkFont(size=10),
            text_color="gray",
            anchor="w",
        )
        self._context._pedigree_tree_node_count_label.grid(
            row=3, column=0, sticky="w", padx=8, pady=(0, 8)
        )

    def _format_pedigree_summary(self, result: PedigreeAnalysisResult) -> str:
        picker_label = (
            "old-school Gaussian" if result.settings.uses_old_school_peak_picker else "modern NB"
        )
        parts = [
            f"{result.n_chromatograms:,} chromatograms · channel {result.channel} · picker={picker_label} · null RT threshold={result.settings.tolerance:g} {result.settings.time_unit}"
        ]
        if result.settings.uses_modern_peak_picker:
            parts[0] += f" · α={result.settings.alpha:g}"
        if result.settings.uses_modern_peak_picker and (
            result.settings.min_prominence > 0 or result.settings.min_pct_area > 0
        ):
            parts.append(
                f"quality: prom≥{result.settings.min_prominence:g}, %area≥{result.settings.min_pct_area:g}"
            )
        if result.isoform_label != "All":
            parts.append(f"isoform={result.isoform_label}")
        tier_bits = []
        for summary in result.tier_summaries:
            tier_bits.append(
                f"tier {summary.tier}: pass={summary.pass_count} fail={summary.fail_count} pruned={summary.pruned_count}"
            )
        if tier_bits:
            parts.append(" · ".join(tier_bits))
        return "\n".join(parts)

    def _update_pedigree_graphviz_banner(self) -> None:
        if self._context._pedigree_graphviz_banner is None:
            return
        if graphviz_available():
            self._context._pedigree_graphviz_banner.configure(text="")
            self._context._pedigree_graphviz_banner.grid_remove()
        else:
            self._context._pedigree_graphviz_banner.configure(
                text=f"⚠ {graphviz_install_hint()}", text_color="#B8860B"
            )
            self._context._pedigree_graphviz_banner.grid()

    def _pedigree_tree_render_options(self) -> PedigreeTreeRenderOptions:
        max_tier = (
            int(round(self._context._pedigree_tree_tier_slider.get()))
            if self._context._pedigree_tree_tier_slider
            else 0
        )
        return PedigreeTreeRenderOptions(
            max_display_tier=max_tier,
            include_failed=bool(self._context._pedigree_include_failed_var.get()),
            show_rt=bool(self._context._pedigree_show_rt_var.get()),
        )

    def _configure_pedigree_tier_slider(self, result: PedigreeAnalysisResult) -> None:
        if self._context._pedigree_tree_tier_slider is None:
            return
        max_tier = max_tier_in_records(result.records)
        steps = max(max_tier, 1)
        self._context._pedigree_tree_tier_slider.configure(
            from_=0, to=max_tier, number_of_steps=steps
        )
        default_tier = result.max_display_tier
        if default_tier is None:
            default_tier = build_default_tree_render_options(
                result.records, library_cycle_count=result.library_cycle_count
            ).max_display_tier
        tier_val = min(max(int(default_tier or 0), 0), max_tier)
        self._context._pedigree_tree_tier_slider.set(float(tier_val))
        if self._context._pedigree_tree_tier_label is not None:
            self._context._pedigree_tree_tier_label.configure(text=f"Max tier shown: {tier_val}")

    def _update_pedigree_tree_density_note(self, result: PedigreeAnalysisResult) -> None:
        if (
            self._context._pedigree_tree_dense_note is None
            or self._context._pedigree_tree_node_count_label is None
        ):
            return
        opts = self._pedigree_tree_render_options()
        visible = count_visible_pedigree_nodes(
            result.records,
            include_failed=opts.include_failed,
            max_display_tier=opts.max_display_tier,
        )
        self._context._pedigree_tree_node_count_label.configure(
            text=f"Visible nodes in figure: {visible:,}"
        )
        if not opts.include_failed:
            with_failed = count_visible_pedigree_nodes(
                result.records, include_failed=True, max_display_tier=opts.max_display_tier
            )
            if with_failed > visible:
                self._context._pedigree_tree_dense_note.configure(
                    text=f"Showing passed nodes only ({visible:,} of {with_failed:,} visible with failed trim points). Enable failed trim points to see red/yellow boundaries."
                )
                return
        self._context._pedigree_tree_dense_note.configure(text="")

    def _on_pedigree_tier_slider_changed(self, value: float) -> None:
        tier = int(round(float(value)))
        if self._context._pedigree_tree_tier_label is not None:
            self._context._pedigree_tree_tier_label.configure(text=f"Max tier shown: {tier}")
        if self._context._pedigree_result is not None:
            self._update_pedigree_tree_density_note(self._context._pedigree_result)
            self._invalidate_pedigree_visualization()

    def _on_pedigree_tree_option_changed(self) -> None:
        if self._context._pedigree_result is not None:
            self._update_pedigree_tree_density_note(self._context._pedigree_result)
            self._invalidate_pedigree_visualization()

    def _invalidate_pedigree_visualization(self) -> None:
        """Clear a plot made with superseded display options."""
        result = self._context._pedigree_result
        self._context._pedigree_viz_artifact = None
        if result is not None:
            result.tree_image_path = None
            result.tree_render_engine = None
            result.tree_render_note = None
        self._show_pedigree_tree_placeholder(
            "Display options changed. Click Generate plot in the sidebar."
        )
        self._context._update_action_states()

    def _render_pedigree_tree_image(
        self,
        result: PedigreeAnalysisResult,
        tree_path: Path,
        *,
        fmt: str = "png",
        options: Optional[PedigreeTreeRenderOptions] = None,
        progress_callback=None,
    ):
        """Render a pedigree tree with supplied or current display controls."""
        opts = options or self._pedigree_tree_render_options()
        result.max_display_tier = opts.max_display_tier
        render_out = render_pedigree_tree(
            result.records,
            tree_path,
            fmt=fmt,
            max_display_tier=opts.max_display_tier,
            include_failed=opts.include_failed,
            show_rt=opts.show_rt,
            progress_callback=progress_callback,
        )
        result.tree_image_path = render_out.path
        result.tree_render_engine = render_out.engine
        result.tree_render_note = render_out.detail
        return render_out

    def _on_run_pedigree(self) -> None:
        if self._context._is_busy():
            return
        if (
            self._context._data_store is None
            or self._context._db_path is None
            or self._context._config is None
        ):
            return
        if not self._context._config.pedigree_configured():
            messagebox.showinfo(
                "Pedigree",
                "Map BB1..BBn columns in Configure Spreadsheet before running pedigree.",
                parent=self._context,
            )
            return
        if not pedigree_backend_available():
            messagebox.showerror(
                "Pedigree",
                "The Rust lcseq extension is required.\n\nSee dev/DEVELOPER_SETUP.md.",
                parent=self._context,
            )
            return
        settings = self._callbacks.parse_settings()
        if settings is None:
            return
        channel = self._context._pedigree_channel_var.get().strip()
        if self._context._cached_scan is not None and channel:
            if channel not in self._context._cached_scan.channel_names:
                messagebox.showinfo(
                    "Pedigree",
                    f"Channel “{channel}” is not in the cached library scan.\n\nAvailable: {', '.join(self._context._cached_scan.channel_names) or 'none'}.\n\nRe-run library scan with this channel selected, or clear the scan to read chromatograms from the database.",
                    parent=self._context,
                )
                return
        if self._context._data_store.get_compound_count() == 0:
            messagebox.showinfo("Pedigree", "The database has no compounds.", parent=self._context)
            return
        n = self._context._data_store.get_compound_count()
        if not messagebox.askyesno(
            "Pedigree analysis",
            f"Run full-library pedigree evaluation on {n:,} compound(s)?",
            parent=self._context,
        ):
            return
        self._start_pedigree_analysis(settings)

    def _start_pedigree_analysis(self, settings: AnalysisSettings) -> None:
        assert self._context._db_path is not None and self._context._config is not None
        scan = self._context._cached_scan
        loading_detail = (
            "Building chromatogram map from scan and evaluating pedigree…"
            if scan is not None
            else "Loading chromatograms from database and evaluating pedigree…"
        )
        self._context._show_loading_page("Running pedigree RT assignment", loading_detail)
        if self._context._pedigree_status_label is not None:
            self._context._pedigree_status_label.configure(text="Pedigree analysis running…")
        self._context._update_action_states()
        db_path = self._context._db_path
        config = self._context._config

        def worker() -> None:
            try:

                def progress(step: int, total: int, status: str) -> None:
                    fraction = step / total if total > 0 else 0.0
                    self._context._thread_loading_progress(
                        min(0.93, fraction), status or "Evaluating pedigree…"
                    )

                result = run_pedigree_analysis_for_path(
                    db_path,
                    config,
                    settings,
                    scan=scan,
                    progress_callback=progress,
                    isoform_label="All",
                )
                tree_opts = build_default_tree_render_options(
                    result.records, library_cycle_count=result.library_cycle_count
                )
                result.max_display_tier = tree_opts.max_display_tier
                self._context._bind_worker_callback(self._on_pedigree_ready, result, tree_opts)
            except LibraryOperationCancelled:
                raise
            except Exception as exc:
                logger.error("Pedigree analysis failed: %s", exc, exc_info=True)
                self._context._bind_worker_callback(self._on_pedigree_failed, str(exc))

        self._context._start_worker(worker)

    def _on_pedigree_ready(
        self, result: PedigreeAnalysisResult, tree_opts: Optional[PedigreeTreeRenderOptions] = None
    ) -> None:
        self._context._worker_thread = None
        self._context._pedigree_result = result
        self._context._pedigree_snapshot_path = None
        self._update_pedigree_graphviz_banner()
        # Restore the content tabview before painting the results card.
        self._context._hide_loading_page()
        self._callbacks.update_rt_results(pedigree_result=result)
        if tree_opts is not None:
            self._context._pedigree_show_rt_var.set(tree_opts.show_rt)
            self._context._pedigree_include_failed_var.set(tree_opts.include_failed)
            self._configure_pedigree_tier_slider(result)
            self._update_pedigree_tree_density_note(result)
        self._display_pedigree_result(result)
        self._context._pedigree_viz_artifact = None
        self._show_pedigree_tree_placeholder(
            "Pedigree RT assignment ready. Click Generate plot in the sidebar."
        )
        if self._context._pedigree_status_label is not None:
            picker = result.settings.peak_picking_algorithm
            status = f"Pedigree RT assignment ready — {len(result.records):,} nodes, {result.n_chromatograms:,} chromatograms. Analysis mode: Pedigree. Peak picking mode: {self._context._format_peak_picking_mode_label(picker)}."
            status += " Generate the pedigree plot from its visualization tab."
            self._context._pedigree_status_label.configure(
                text=status, text_color=("gray10", "gray90")
            )
        if self._context._content_tabview is not None:
            try:
                self._context._content_tabview.set(_TAB_RT_ASSIGNMENT)
            except ValueError:
                pass
        self._context._update_action_states()
        self._callbacks.update_split_tree_status()
        self._context._schedule_on_main(self._callbacks.ensure_del_cycle_tree)

    def _on_generate_pedigree_plot(self) -> None:
        """Render the pedigree visualization only after an explicit user action."""
        result = self._context._pedigree_result
        db_path = self._context._db_path
        if result is None or db_path is None or self._context._is_busy():
            return
        options = self._pedigree_tree_render_options()
        tree_path = session_pedigree_dir(db_path) / "pedigree_tree.png"
        self._context._pedigree_viz_artifact = None
        result.tree_image_path = None
        result.tree_render_engine = None
        result.tree_render_note = None
        self._show_pedigree_tree_placeholder("Generating pedigree plot…")
        self._context._show_loading_page(
            "Generating pedigree plot",
            "Preparing pedigree layout…",
        )
        self._context._update_action_states()

        def worker() -> None:
            try:

                def export_progress(fraction: float, status: str) -> None:
                    self._context._thread_loading_progress(
                        min(0.55, 0.02 + 0.53 * fraction),
                        status or "Rendering pedigree export image…",
                    )

                def preview_progress(fraction: float, status: str) -> None:
                    self._context._thread_loading_progress(
                        min(0.98, 0.58 + 0.40 * fraction),
                        status or "Building interactive pedigree preview…",
                    )

                self._context._thread_loading_progress(
                    0.02, "Writing pedigree export image…"
                )
                render_out = self._render_pedigree_tree_image(
                    result,
                    tree_path,
                    options=options,
                    progress_callback=export_progress,
                )
                self._context._thread_loading_progress(
                    0.58, "Building interactive pedigree preview…"
                )
                preview_figure = build_pedigree_tree_matplotlib_figure(
                    result.records,
                    max_display_tier=options.max_display_tier,
                    include_failed=options.include_failed,
                    show_rt=options.show_rt,
                    progress_callback=preview_progress,
                )
                self._context._thread_loading_progress(0.99, "Mounting pedigree plot…")
                self._context._bind_worker_callback(
                    self._on_pedigree_plot_ready,
                    result,
                    render_out.engine,
                    preview_figure,
                )
            except Exception as exc:
                logger.error("Pedigree plot generation failed: %s", exc, exc_info=True)
                self._context._bind_worker_callback(self._on_pedigree_plot_failed, str(exc))

        self._context._start_worker(worker)

    def _on_pedigree_plot_ready(
        self,
        result: PedigreeAnalysisResult,
        render_engine: str,
        preview_figure=None,
    ) -> None:
        """Publish and display a completed pedigree visualization."""
        self._context._worker_thread = None
        self._update_pedigree_graphviz_banner()
        self._update_pedigree_tree_density_note(result)
        if preview_figure is not None:
            self._mount_pedigree_tree_figure(preview_figure)
        else:
            self._show_pedigree_tree_preview(result)
        try:
            self._callbacks.capture_visualization(result)
        except Exception as exc:
            logger.warning("Could not capture pedigree report artifact: %s", exc)
        if self._context._pedigree_status_label is not None:
            self._context._pedigree_status_label.configure(
                text=f"Pedigree plot ready ({render_engine}).",
                text_color=("gray10", "gray90"),
            )
        self._context._hide_loading_page()
        self._context._update_action_states()

    def _on_pedigree_plot_failed(self, message: str) -> None:
        """Restore the UI after pedigree plot generation fails."""
        self._context._worker_thread = None
        self._show_pedigree_tree_placeholder("Pedigree plot could not be generated.")
        self._context._hide_loading_page()
        self._context._update_action_states()
        show_error(
            self._context,
            "Pedigree plot",
            message,
            what_to_do=(
                None
                if graphviz_available()
                else (
                    "Install Graphviz for the preferred layout "
                    "(see dev/DEVELOPER_SETUP.md). Without it, LC-Seq uses "
                    "a matplotlib tier-ring preview."
                )
            ),
        )

    def _build_del_cycle_artifacts_after_pedigree(self) -> None:
        """Build split-tree data for exports without blocking the UI."""
        self._callbacks.ensure_del_cycle_tree()

    def _on_pedigree_failed(self, message: str) -> None:
        self._context._worker_thread = None
        if self._context._pedigree_status_label is not None:
            self._context._pedigree_status_label.configure(text=message, text_color="#D29922")
        self._context._hide_loading_page()
        messagebox.showerror("Pedigree analysis", message, parent=self._context)
        self._context._update_action_states()

    def _display_pedigree_result(self, result: PedigreeAnalysisResult) -> None:
        self._qc_panel._clear_frame_children(self._context._pedigree_frame)
        if self._context._pedigree_frame is not None:
            total_pass = sum((s.pass_count for s in result.tier_summaries))
            total_fail = sum((s.fail_count for s in result.tier_summaries))
            total_pruned = sum((s.pruned_count for s in result.tier_summaries))
            header = self._qc_panel._make_info_card(
                self._context._pedigree_frame,
                "Library totals",
                f"{len(result.records):,} nodes — passed={total_pass:,}, failed={total_fail:,}, pruned={total_pruned:,} · engine {result.backend_name}",
                wraplength=_SIDEBAR_WRAP,
            )
            header.pack(fill="x", pady=(0, 8))
            if result.tier_summaries:
                self._make_tier_summary_panel(self._context._pedigree_frame, result.tier_summaries)
            else:
                ctk.CTkLabel(
                    self._context._pedigree_frame,
                    text="No per-tier counts were returned for this run.",
                    font=ctk.CTkFont(size=11),
                    text_color="gray",
                    anchor="w",
                    wraplength=_SIDEBAR_WRAP,
                    justify="left",
                ).pack(fill="x", pady=4)

    def _make_tier_summary_panel(
        self, parent: ctk.CTkFrame, summaries: List[PedigreeTierSummary]
    ) -> ctk.CTkFrame:
        """Per-tier pass / fail / pruned counts (one row per coupling cycle)."""
        card = ctk.CTkFrame(parent, corner_radius=10)
        card.pack(fill="x", pady=4)
        card.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            card, text="By coupling tier", font=ctk.CTkFont(size=13, weight="bold"), anchor="w"
        ).grid(row=0, column=0, padx=12, pady=(10, 2), sticky="w")
        ctk.CTkLabel(
            card,
            text="Each tier is one coupling cycle in the pedigree tree. Passed = RT-consistent nodes; failed = synthesis dropped; pruned = unevaluated because a parent failed.",
            font=ctk.CTkFont(size=10),
            text_color="gray",
            anchor="w",
            wraplength=_SIDEBAR_WRAP,
            justify="left",
        ).grid(row=1, column=0, padx=12, pady=(0, 6), sticky="w")
        table = ctk.CTkFrame(card, fg_color="transparent")
        table.grid(row=2, column=0, padx=12, pady=(0, 10), sticky="ew")
        for col, weight in enumerate((0, 1, 1, 1)):
            table.grid_columnconfigure(col, weight=weight)
        for col, title in enumerate(("Tier", "Pass", "Fail", "Prune")):
            ctk.CTkLabel(
                table,
                text=title,
                font=ctk.CTkFont(size=11, weight="bold"),
                anchor="e" if col else "w",
            ).grid(row=0, column=col, padx=(0 if col == 0 else 4, 0), pady=(0, 4), sticky="ew")
        for row_idx, summary in enumerate(summaries, start=1):
            values = (
                str(summary.tier),
                f"{summary.pass_count:,}",
                f"{summary.fail_count:,}",
                f"{summary.pruned_count:,}",
            )
            for col, value in enumerate(values):
                ctk.CTkLabel(
                    table,
                    text=value,
                    font=ctk.CTkFont(size=12, weight="bold" if col else "normal"),
                    anchor="e" if col else "w",
                ).grid(row=row_idx, column=col, padx=(0 if col == 0 else 4, 0), pady=2, sticky="ew")
        return card

    def _clear_pedigree_tree_plot(self) -> None:
        """Release matplotlib canvas/toolbar used for the interactive tree preview."""
        if self._context._pedigree_figure_host is not None:
            self._context._pedigree_figure_host.clear()

    def _show_pedigree_tree_placeholder(self, message: str) -> None:
        if self._context._pedigree_figure_host is not None:
            self._context._pedigree_figure_host.show_placeholder(message)

    def _mount_pedigree_tree_figure(self, figure) -> None:
        """Embed a matplotlib figure with pan/zoom toolbar in the pedigree tab."""
        if self._context._pedigree_figure_host is not None:
            self._context._pedigree_figure_host.mount(figure)

    def _show_pedigree_tree_preview(self, result: PedigreeAnalysisResult) -> None:
        if self._context._pedigree_tree_host is None:
            return
        if not result.records:
            self._show_pedigree_tree_placeholder("No pedigree nodes to display.")
            return
        image_path = result.tree_image_path
        if image_path is None or not Path(image_path).is_file():
            if result.tree_render_engine != "matplotlib":
                message = (
                    result.tree_render_note
                    or "Tree image could not be generated. Check logs for details."
                )
                self._show_pedigree_tree_placeholder(message)
                return
        try:
            opts = self._pedigree_tree_render_options()
            figure = build_pedigree_tree_preview_figure(
                result.records,
                image_path,
                render_engine=result.tree_render_engine,
                max_display_tier=opts.max_display_tier,
                include_failed=opts.include_failed,
                show_rt=opts.show_rt,
            )
            self._mount_pedigree_tree_figure(figure)
        except Exception as exc:
            logger.warning("Could not build interactive pedigree tree preview: %s", exc)
            fallback = (
                f"Tree saved at:\n{image_path}"
                if image_path
                else "Tree preview could not be built."
            )
            self._show_pedigree_tree_placeholder(fallback)

    def _on_export_pedigree_csv(self) -> None:
        if self._context._pedigree_result is None:
            return
        dest = filedialog.asksaveasfilename(
            parent=self._context,
            title="Export pedigree CSV",
            defaultextension=".csv",
            filetypes=[("CSV", "*.csv")],
        )
        if not dest:
            return
        try:
            export_pedigree_csv(self._context._pedigree_result, dest)
            messagebox.showinfo("Pedigree", f"Saved to:\n{dest}", parent=self._context)
        except Exception as exc:
            messagebox.showerror("Pedigree", str(exc), parent=self._context)

    def _on_export_pedigree_tree(self) -> None:
        if self._context._pedigree_result is None:
            return
        if not show_graphviz_missing_warning(self._context, for_export=True):
            return
        dest = filedialog.asksaveasfilename(
            parent=self._context,
            title="Export pedigree tree",
            defaultextension=".png",
            filetypes=[("PNG", "*.png"), ("SVG vector", "*.svg"), ("PDF", "*.pdf")],
        )
        if not dest:
            return
        try:
            fmt = Path(dest).suffix.lstrip(".") or "png"
            opts = self._pedigree_tree_render_options()
            render_out = render_pedigree_tree(
                self._context._pedigree_result.records,
                Path(dest),
                fmt=fmt,
                max_display_tier=opts.max_display_tier,
                include_failed=opts.include_failed,
                show_rt=opts.show_rt,
            )
            show_info(
                self._context, "Pedigree", f"Saved to:\n{render_out.path}\n\n({render_out.engine})"
            )
        except Exception as exc:
            show_error(
                self._context,
                "Pedigree",
                str(exc),
                what_to_do=(
                    None
                    if graphviz_available()
                    else "Install Graphviz for the preferred layout (see dev/DEVELOPER_SETUP.md), or export again with the matplotlib fallback."
                ),
            )
