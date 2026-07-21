# src/ui/library_analysis/window_shell.py
"""Shared shell, tab, sidebar, and navigation construction."""

from __future__ import annotations

import tkinter as tk
from pathlib import Path
from typing import Optional, Protocol, Tuple

import customtkinter as ctk

from src.ui.busy_overlay import BusyOverlay
from src.ui.library_analysis.figure_host import FigureHost, build_tree_figure_host

_TAB_METRICS = "Library QC metrics"
_TAB_PLOTS = "Library QC visualizations"
_TAB_RT_ASSIGNMENT = "RT assignment"
_TAB_PEDIGREE_VIZ = "Pedigree visualization"
_TAB_SPLITTREE_VIZ = "Split-tree visualization"
_SIDEBAR_WRAP = 280
_SECTION_HEADER_COLOR = ("#0969da", "#58a6ff")
_MAIN_SIDEBAR_MINSIZE = 240
_MAIN_CONTENT_MINSIZE = 520
_PLOT_LIST_MINSIZE = 180
_PLOT_PREVIEW_MINSIZE = 360


class WindowShellHost(Protocol):
    """Host capabilities consumed while constructing the shared window shell."""

    def _ui_is_active(self) -> bool:
        """Return whether the window can still receive UI updates."""
        ...

    def _focus_tab(self, tab_name: str) -> None:
        """Focus a result tab."""
        ...


def _paned_sash_bg() -> str:
    """Return the appearance-aware Tk paned-window sash color."""
    return "#3d3d3d" if ctk.get_appearance_mode() == "Dark" else "#c0c0c0"


def _create_horizontal_paned(
    parent: ctk.CTkFrame,
    *,
    left_minsize: int,
    right_minsize: int,
) -> Tuple[tk.PanedWindow, ctk.CTkFrame, ctk.CTkFrame]:
    """Return a horizontal paned window and its two CTk hosts."""
    paned = tk.PanedWindow(
        parent,
        orient=tk.HORIZONTAL,
        sashwidth=8,
        sashrelief=tk.RAISED,
        opaqueresize=True,
        bg=_paned_sash_bg(),
        bd=0,
        showhandle=False,
    )
    paned.pack(fill="both", expand=True)
    left = ctk.CTkFrame(paned, fg_color="transparent")
    right = ctk.CTkFrame(paned, fg_color="transparent")
    paned.add(left, minsize=left_minsize, stretch="always")
    paned.add(right, minsize=right_minsize, stretch="always")
    return paned, left, right


def _section_header_font() -> ctk.CTkFont:
    """Create the shared section header font."""
    return ctk.CTkFont(size=14, weight="bold")


def _primary_action_font() -> ctk.CTkFont:
    """Create the shared primary action font."""
    return ctk.CTkFont(size=14, weight="bold")


class WindowShell:
    """Construct and coordinate shared Library Analysis window chrome."""

    def __init__(self, host: WindowShellHost) -> None:
        self._host = host

    def _build_top_bar(self, db_path: str) -> None:
        """Header row: title, global actions, and database context."""
        bar = ctk.CTkFrame(self._host, fg_color=("gray92", "gray18"))
        bar.grid(row=0, column=0, sticky="ew", padx=16, pady=(10, 8))
        bar.grid_columnconfigure(2, weight=1)

        title_row = ctk.CTkFrame(bar, fg_color="transparent")
        title_row.grid(row=0, column=0, padx=(12, 16), pady=8, sticky="w")

        ctk.CTkLabel(
            title_row,
            text="Library Analysis",
            font=ctk.CTkFont(size=20, weight="bold"),
        ).pack(side="left", padx=(0, 16))

        self._host._scan_btn = ctk.CTkButton(
            title_row,
            text="Run library scan",
            width=150,
            height=32,
            font=_primary_action_font(),
            fg_color="#238636",
            hover_color="#2ea043",
            command=self._host._qc_panel._on_run_library_scan,
        )
        self._host._scan_btn.pack(side="left", padx=(0, 8))
        self._host._busy_sensitive_widgets.append(self._host._scan_btn)

        self._host._clear_scan_btn = ctk.CTkButton(
            title_row,
            text="Clear scan",
            width=96,
            height=32,
            fg_color="gray40",
            command=self._host._qc_panel._on_clear_library_scan,
        )
        self._host._clear_scan_btn.pack(side="left", padx=(0, 4))
        self._host._busy_sensitive_widgets.append(self._host._clear_scan_btn)

        self._host._export_scan_btn = ctk.CTkButton(
            title_row,
            text="Export scan…",
            width=108,
            height=32,
            fg_color="gray40",
            command=self._host._qc_panel._on_export_library_scan,
        )
        self._host._export_scan_btn.pack(side="left", padx=(0, 4))
        self._host._busy_sensitive_widgets.append(self._host._export_scan_btn)

        self._host._import_scan_btn = ctk.CTkButton(
            title_row,
            text="Import scan…",
            width=108,
            height=32,
            fg_color="gray40",
            command=self._host._qc_panel._on_import_library_scan,
        )
        self._host._import_scan_btn.pack(side="left", padx=(0, 8))
        self._host._busy_sensitive_widgets.append(self._host._import_scan_btn)

        self._host._export_report_btn = ctk.CTkButton(
            title_row,
            text="Generate report…",
            width=150,
            height=32,
            fg_color="gray40",
            command=self._host._report_controller._on_export_report,
        )
        self._host._export_report_btn.pack(side="left")
        self._host._busy_sensitive_widgets.append(self._host._export_report_btn)

        kind = "Index" if self._host._index_db_mode else "Full"
        fname = Path(db_path).name
        channels = ", ".join(self._host._config.count_names) if self._host._config else ""
        ctk.CTkLabel(
            bar,
            text=f"Database: {fname} ({kind})  ·  Channels: {channels}",
            font=ctk.CTkFont(size=12),
            anchor="e",
            justify="right",
        ).grid(row=0, column=2, padx=12, pady=8, sticky="e")

    def _build_body_shell(self) -> None:
        """Resizable split between the left option sidebar and tab content."""
        host = ctk.CTkFrame(self._host, fg_color="transparent")
        host.grid(row=1, column=0, sticky="nsew", padx=16, pady=(0, 12))
        host.grid_columnconfigure(0, weight=1)
        host.grid_rowconfigure(0, weight=1)

        self._host._body_paned, sidebar_host, content_host = _create_horizontal_paned(
            host,
            left_minsize=_MAIN_SIDEBAR_MINSIZE,
            right_minsize=_MAIN_CONTENT_MINSIZE,
        )
        self._build_left_sidebar(sidebar_host)
        self._build_right_content(content_host)

    def _set_initial_paned_positions(self) -> None:
        """Place paned-window sashes after the first layout pass."""
        if not self._host._ui_is_active():
            return
        try:
            if self._host._body_paned is not None:
                total = self._host._body_paned.winfo_width()
                if total > _MAIN_SIDEBAR_MINSIZE + _MAIN_CONTENT_MINSIZE:
                    self._host._body_paned.sash_place(0, int(total * 0.28), 0)
            if self._host._plots_body_paned is not None:
                total = self._host._plots_body_paned.winfo_width()
                if total > _PLOT_LIST_MINSIZE + _PLOT_PREVIEW_MINSIZE:
                    self._host._plots_body_paned.sash_place(
                        0,
                        min(220, int(total * 0.22)),
                        0,
                    )
        except tk.TclError:
            pass

    def _build_left_sidebar(self, parent: ctk.CTkFrame) -> None:
        """Left column: tab-specific analysis options."""
        shell = ctk.CTkFrame(parent, corner_radius=10)
        self._host._control_panel = shell
        shell.pack(fill="both", expand=True, padx=(0, 8))
        shell.grid_rowconfigure(0, weight=1)
        shell.grid_columnconfigure(0, weight=1)

        stack = ctk.CTkFrame(shell, fg_color="transparent")
        stack.grid(row=0, column=0, sticky="nsew", padx=4, pady=4)
        stack.grid_rowconfigure(0, weight=1)
        stack.grid_columnconfigure(0, weight=1)
        self._host._sidebar_stack = stack

        self._host._metrics_sidebar = ctk.CTkScrollableFrame(
            stack,
            label_text="Library QC metrics",
            label_font=_section_header_font(),
            label_text_color=_SECTION_HEADER_COLOR,
        )
        self._host._plots_sidebar = ctk.CTkScrollableFrame(
            stack,
            label_text="Library QC visualizations",
            label_font=_section_header_font(),
            label_text_color=_SECTION_HEADER_COLOR,
        )
        self._host._rt_assignment_sidebar = ctk.CTkScrollableFrame(
            stack,
            label_text="RT assignment",
            label_font=_section_header_font(),
            label_text_color=_SECTION_HEADER_COLOR,
        )
        self._host._pedigree_viz_sidebar = ctk.CTkScrollableFrame(
            stack,
            label_text="Pedigree visualization",
            label_font=_section_header_font(),
            label_text_color=_SECTION_HEADER_COLOR,
        )
        self._host._splittree_viz_sidebar = ctk.CTkScrollableFrame(
            stack,
            label_text="Split-tree visualization",
            label_font=_section_header_font(),
            label_text_color=_SECTION_HEADER_COLOR,
        )
        for panel in (
            self._host._metrics_sidebar,
            self._host._plots_sidebar,
            self._host._rt_assignment_sidebar,
            self._host._pedigree_viz_sidebar,
            self._host._splittree_viz_sidebar,
        ):
            panel.grid_columnconfigure(0, weight=1)

        self._host._qc_panel._build_metrics_sidebar_content(self._host._metrics_sidebar)
        self._host._qc_panel._build_plots_sidebar_content(self._host._plots_sidebar)
        self._host._rt_assignment_panel._build_rt_assignment_sidebar_content(
            self._host._rt_assignment_sidebar
        )
        self._host._pedigree_panel._build_pedigree_viz_sidebar_content(
            self._host._pedigree_viz_sidebar
        )
        self._host._splittree_panel._build_splittree_viz_sidebar_content(
            self._host._splittree_viz_sidebar
        )
        self._host._pedigree_sidebar = self._host._rt_assignment_sidebar
        self._show_sidebar_for_tab(_TAB_METRICS)

        self._host._status_label = ctk.CTkLabel(
            shell,
            text="No scan loaded.",
            font=ctk.CTkFont(size=10),
            text_color="gray",
            anchor="w",
            wraplength=_SIDEBAR_WRAP,
            justify="left",
        )
        self._host._status_label.grid(row=1, column=0, padx=12, pady=(4, 10), sticky="w")

    def _show_sidebar_for_tab(self, tab_name: str) -> None:
        panels = {
            _TAB_METRICS: self._host._metrics_sidebar,
            _TAB_PLOTS: self._host._plots_sidebar,
            _TAB_RT_ASSIGNMENT: self._host._rt_assignment_sidebar,
            _TAB_PEDIGREE_VIZ: self._host._pedigree_viz_sidebar,
            _TAB_SPLITTREE_VIZ: self._host._splittree_viz_sidebar,
        }
        for name, panel in panels.items():
            if panel is None:
                continue
            if name == tab_name:
                panel.grid(row=0, column=0, sticky="nsew")
            else:
                panel.grid_remove()

    def _on_main_tab_changed(self) -> None:
        if self._host._content_tabview is None:
            return
        try:
            tab = self._host._content_tabview.get()
        except (ValueError, tk.TclError):
            return
        self._show_sidebar_for_tab(tab)
        if tab == _TAB_SPLITTREE_VIZ:
            self._host._splittree_panel._show_splittree_placeholder(
                "Choose RT source and click Generate plot in the sidebar."
            )

    def _build_rt_and_viz_tabs(self, tk_bg: str) -> None:
        """RT assignment, pedigree visualization, and split-tree visualization tabs."""
        assert self._host._content_tabview is not None and self._host._config is not None

        rt_tab = self._host._content_tabview.add(_TAB_RT_ASSIGNMENT)
        rt_tab.grid_columnconfigure(0, weight=1)
        rt_tab.grid_rowconfigure(1, weight=1)

        rt_toolbar = ctk.CTkFrame(rt_tab, fg_color="transparent")
        rt_toolbar.grid(row=0, column=0, sticky="ew", padx=8, pady=(6, 4))
        rt_toolbar.grid_columnconfigure(0, weight=1)

        self._host._pedigree_summary_label = ctk.CTkLabel(
            rt_toolbar,
            text="Configure peak picking and analysis mode in the sidebar, then run RT assignment.",
            font=ctk.CTkFont(size=12),
            text_color="gray",
            anchor="w",
            wraplength=760,
            justify="left",
        )
        self._host._pedigree_summary_label.grid(row=0, column=0, sticky="ew", pady=(0, 6))

        rt_actions = ctk.CTkFrame(rt_toolbar, fg_color="transparent")
        rt_actions.grid(row=1, column=0, sticky="w")

        self._host._export_rts_btn = ctk.CTkButton(
            rt_actions,
            text="Export RTs…",
            width=130,
            fg_color="gray40",
            state="disabled",
            command=self._host._rt_assignment_panel._on_export_assigned_rts,
        )
        self._host._export_rts_btn.pack(side="left", padx=(0, 6))
        self._host._busy_sensitive_widgets.append(self._host._export_rts_btn)

        self._host._pedigree_export_del_csv_btn = ctk.CTkButton(
            rt_actions,
            text="Export analysis bundle…",
            width=170,
            fg_color="gray40",
            state="disabled",
            command=self._host._splittree_panel._on_export_del_cycle_csv,
        )
        self._host._pedigree_export_del_csv_btn.pack(side="left", padx=(0, 6))
        self._host._busy_sensitive_widgets.append(self._host._pedigree_export_del_csv_btn)

        self._host._pedigree_help_btn = ctk.CTkButton(
            rt_actions,
            text="Help ▾",
            width=100,
            fg_color="gray40",
            command=self._host._pedigree_panel._show_pedigree_help_menu,
        )
        self._host._pedigree_help_btn.pack(side="left", padx=(0, 6))

        rt_body = ctk.CTkScrollableFrame(rt_tab, label_text="Assignment results")
        rt_body.grid(row=1, column=0, sticky="nsew", padx=8, pady=(0, 8))
        rt_body.grid_columnconfigure(0, weight=1)
        self._host._rt_assignment_results_label = ctk.CTkLabel(
            rt_body,
            text="No RT assignment run yet.",
            font=ctk.CTkFont(size=12),
            text_color="gray",
            anchor="nw",
            wraplength=760,
            justify="left",
        )
        self._host._rt_assignment_results_label.grid(row=0, column=0, sticky="ew", padx=8, pady=8)

        # --- Pedigree visualization tab ---
        ped_viz_tab = self._host._content_tabview.add(_TAB_PEDIGREE_VIZ)
        ped_viz_tab.grid_columnconfigure(0, weight=1)
        ped_viz_tab.grid_rowconfigure(0, weight=1)

        ped_viz_body = ctk.CTkFrame(ped_viz_tab, fg_color="transparent")
        ped_viz_body.grid(row=0, column=0, sticky="nsew", padx=8, pady=(6, 8))
        ped_viz_body.grid_columnconfigure(0, weight=1)
        ped_viz_body.grid_rowconfigure(0, weight=1)

        (
            self._host._pedigree_tree_host,
            self._host._pedigree_tree_placeholder,
            self._host._pedigree_tree_plot_host,
            self._host._pedigree_tree_header_label,
        ) = build_tree_figure_host(
            ped_viz_body,
            tk_bg=tk_bg,
            title="Pedigree tier-ring",
            subtitle="Configure display options, then generate the plot from the sidebar.",
            placeholder="Run pedigree RT assignment, then click Generate plot in the sidebar.",
        )
        self._host._pedigree_figure_host = FigureHost(
            self._host._pedigree_tree_plot_host,
            self._host._pedigree_tree_placeholder,
        )

        # --- Split-tree visualization tab ---
        self._host._splittree_panel._build_splittree_tab(self._host._content_tabview, tk_bg)

    def _build_right_content(self, parent: ctk.CTkFrame) -> None:
        """Right column: metrics and visualization tabs."""
        shell = ctk.CTkFrame(parent, fg_color="transparent")
        self._host._results_shell = shell
        shell.pack(fill="both", expand=True, padx=(8, 0))
        shell.grid_columnconfigure(0, weight=1)
        shell.grid_rowconfigure(0, weight=1)

        self._host._content_tabview = ctk.CTkTabview(
            shell, corner_radius=10, command=self._on_main_tab_changed
        )
        self._host._content_tabview.grid(row=0, column=0, sticky="nsew")
        shell.bind("<Configure>", self._on_results_shell_resize)

        metrics_tab = self._host._content_tabview.add(_TAB_METRICS)
        metrics_tab.grid_columnconfigure(0, weight=1)
        metrics_tab.grid_rowconfigure(1, weight=1)
        metrics_tab.grid_rowconfigure(0, weight=0)

        metrics_toolbar = ctk.CTkFrame(metrics_tab, fg_color="transparent")
        metrics_toolbar.grid(row=0, column=0, sticky="ew", padx=8, pady=(6, 4))
        metrics_toolbar.grid_columnconfigure(0, weight=1)

        self._host._metrics_summary_label = ctk.CTkLabel(
            metrics_toolbar,
            text="Summary metrics appear after Calculate metrics.",
            font=ctk.CTkFont(size=12),
            text_color="gray",
            anchor="w",
        )
        self._host._metrics_summary_label.grid(row=0, column=0, sticky="w", pady=(0, 6))

        metrics_actions = ctk.CTkFrame(metrics_toolbar, fg_color="transparent")
        metrics_actions.grid(row=1, column=0, sticky="w")

        self._host._export_metrics_csv_btn = ctk.CTkButton(
            metrics_actions,
            text="Export metrics CSV…",
            width=150,
            fg_color="#0969da",
            hover_color="#1f6feb",
            state="disabled",
            command=self._host._qc_panel._on_export_metrics_csv,
        )
        self._host._export_metrics_csv_btn.pack(side="left")
        self._host._busy_sensitive_widgets.append(self._host._export_metrics_csv_btn)

        self._host._metrics_frame = ctk.CTkScrollableFrame(metrics_tab, fg_color="transparent")
        self._host._metrics_frame.grid(row=1, column=0, sticky="nsew")
        self._host._metrics_frame.grid_columnconfigure(0, weight=1)

        plots_tab = self._host._content_tabview.add(_TAB_PLOTS)
        plots_tab.grid_columnconfigure(0, weight=1)
        plots_tab.grid_rowconfigure(1, weight=1)
        plots_tab.grid_rowconfigure(0, weight=0)

        plots_toolbar = ctk.CTkFrame(plots_tab, fg_color="transparent")
        plots_toolbar.grid(row=0, column=0, sticky="ew", padx=8, pady=(6, 4))
        plots_toolbar.grid_columnconfigure(0, weight=1)

        self._host._plots_summary_label = ctk.CTkLabel(
            plots_toolbar,
            text="No plots generated yet.",
            font=ctk.CTkFont(size=12),
            text_color="gray",
            anchor="w",
        )
        self._host._plots_summary_label.grid(
            row=0, column=0, columnspan=2, sticky="ew", pady=(0, 6)
        )

        plots_actions = ctk.CTkFrame(plots_toolbar, fg_color="transparent")
        plots_actions.grid(row=1, column=0, columnspan=2, sticky="ew")

        self._host._plot_export_btn = ctk.CTkButton(
            plots_actions,
            text="Export PNG…",
            width=110,
            fg_color="gray40",
            state="disabled",
            command=self._host._qc_panel._on_export_current_plot,
        )
        self._host._plot_export_btn.pack(side="left", padx=(0, 6))
        self._host._busy_sensitive_widgets.append(self._host._plot_export_btn)

        self._host._export_all_plots_btn = ctk.CTkButton(
            plots_actions,
            text="Export all plots…",
            width=130,
            fg_color="gray40",
            command=self._host._qc_panel._on_export_all_plots,
        )
        self._host._export_all_plots_btn.pack(side="left", padx=(0, 6))
        self._host._busy_sensitive_widgets.append(self._host._export_all_plots_btn)

        self._host._open_plots_folder_btn = ctk.CTkButton(
            plots_actions,
            text="Open plots folder",
            width=120,
            fg_color="gray40",
            command=self._host._qc_panel._on_open_plots_folder,
        )
        self._host._open_plots_folder_btn.pack(side="left")
        self._host._busy_sensitive_widgets.append(self._host._open_plots_folder_btn)

        plot_body = ctk.CTkFrame(plots_tab, fg_color="transparent")
        plot_body.grid(row=1, column=0, sticky="nsew", padx=8, pady=(0, 8))
        plot_body.grid_columnconfigure(0, weight=1)
        plot_body.grid_rowconfigure(0, weight=1)

        self._host._plots_body_paned, plot_list_host, plot_preview_host = _create_horizontal_paned(
            plot_body,
            left_minsize=_PLOT_LIST_MINSIZE,
            right_minsize=_PLOT_PREVIEW_MINSIZE,
        )

        self._host._plot_list_frame = ctk.CTkScrollableFrame(
            plot_list_host,
            label_text="Plots",
            label_font=_section_header_font(),
            label_text_color=_SECTION_HEADER_COLOR,
        )
        self._host._plot_list_frame.pack(fill="both", expand=True, padx=(0, 4))

        preview_col = ctk.CTkFrame(plot_preview_host, corner_radius=8)
        preview_col.pack(fill="both", expand=True)
        preview_col.grid_columnconfigure(0, weight=1)
        preview_col.grid_rowconfigure(2, weight=1)

        self._host._plot_preview_title = ctk.CTkLabel(
            preview_col,
            text="Select a plot from the list",
            font=ctk.CTkFont(size=15, weight="bold"),
            anchor="w",
            wraplength=560,
            justify="left",
        )
        self._host._plot_preview_title.grid(row=0, column=0, sticky="ew", padx=12, pady=(12, 4))

        self._host._plot_preview_help = ctk.CTkLabel(
            preview_col,
            text="",
            font=ctk.CTkFont(size=11),
            text_color="gray",
            anchor="w",
            wraplength=620,
            justify="left",
        )
        self._host._plot_preview_help.grid(row=1, column=0, sticky="ew", padx=12, pady=(0, 8))

        preview_host = ctk.CTkFrame(preview_col, fg_color=("gray90", "gray17"))
        preview_host.grid(row=2, column=0, sticky="nsew", padx=12, pady=(0, 12))
        preview_host.grid_columnconfigure(0, weight=1)
        preview_host.grid_rowconfigure(0, weight=1)

        tk_bg = ctk.ThemeManager.theme["CTkFrame"]["fg_color"][
            1 if ctk.get_appearance_mode() == "Dark" else 0
        ]
        self._host._plot_preview_tk = tk.Label(preview_host, text="", bg=tk_bg, borderwidth=0)
        self._host._plot_preview_tk.grid(row=0, column=0, sticky="nsew", padx=4, pady=4)

        self._build_rt_and_viz_tabs(tk_bg)

        self._host._busy_overlay = BusyOverlay(
            shell,
            on_cancel=self._host._on_cancel_operation,
        )
        self._host._loading_frame = self._host._busy_overlay.frame
        self._host._loading_title = self._host._busy_overlay.title_label
        self._host._loading_detail = self._host._busy_overlay.detail_label
        self._host._loading_bar = self._host._busy_overlay.progress_bar
        self._host._loading_percent = self._host._busy_overlay.percent_label
        self._host._loading_cancel_btn = self._host._busy_overlay.cancel_button

        self._host._progress_label = self._host._loading_detail
        self._host._progress_bar = self._host._loading_bar
        self._host._last_tabview_height = 0
        self._host.after(200, self._sync_tabview_height)

    def _on_results_shell_resize(self, event: tk.Event) -> None:
        if getattr(event, "widget", None) is not self._host._results_shell:
            return
        self._sync_tabview_height(event.height)

    def _sync_tabview_height(self, shell_height: Optional[int] = None) -> None:
        """CTkTabview does not always expand vertically with grid; size it to the shell."""
        if (
            not self._host._ui_is_active()
            or self._host._content_tabview is None
            or self._host._results_shell is None
        ):
            return
        try:
            height = (
                shell_height
                if shell_height is not None
                else self._host._results_shell.winfo_height()
            )
            target = max(320, int(height) - 4)
            if target == self._host._last_tabview_height:
                return
            self._host._last_tabview_height = target
            self._host._content_tabview.configure(height=target)
        except tk.TclError:
            pass
