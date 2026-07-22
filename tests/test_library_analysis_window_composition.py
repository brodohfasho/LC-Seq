# tests/test_library_analysis_window_composition.py
"""Headless tests for Library Analysis composition and action decisions."""

from __future__ import annotations

import ast
import importlib
import inspect
from pathlib import Path

from src.ui.library_analysis.action_state import (
    LibraryActionInputs,
    LibraryActionState,
)


def _inputs(**overrides: bool) -> LibraryActionInputs:
    """Build action facts with every capability disabled by default."""
    values = {field_name: False for field_name in LibraryActionInputs.__dataclass_fields__}
    values.update(overrides)
    return LibraryActionInputs(**values)


def test_busy_state_disables_every_action() -> None:
    """Busy operations must disable all otherwise available actions."""
    inputs = _inputs(
        busy=True,
        has_channels=True,
        has_selected_metrics=True,
        has_selected_plots=True,
        has_scan=True,
        has_scan_cache=True,
        has_snapshot=True,
        has_latest_snapshot=True,
        has_plot_files=True,
        has_computed_metrics=True,
        has_saved_snapshots=True,
        has_report_content=True,
        rt_can_run=True,
        has_rt_result=True,
        has_pedigree=True,
        has_latest_pedigree=True,
        has_pedigree_tree=True,
        has_del_tree=True,
    )

    state = LibraryActionState.decide(inputs)

    assert not any(vars(state).values())


def test_action_dependencies_are_independent() -> None:
    """Each action uses its specific prerequisites rather than a broad fallback."""
    state = LibraryActionState.decide(
        _inputs(
            has_channels=True,
            has_scan=True,
            has_selected_plots=True,
            has_report_content=True,
        )
    )

    assert state.scan
    assert state.generate_plots
    assert state.export_signal_csv
    assert state.export_report
    assert not state.calculate_metrics
    assert not state.save_snapshot
    assert not state.export_pedigree


def test_window_and_composed_modules_import_without_cycle() -> None:
    """The public window import must not introduce panel import cycles."""
    window_module = importlib.import_module("src.ui.library_data_window")
    panel_module = importlib.import_module("src.ui.library_analysis.qc_panel")

    assert window_module.LibraryDataWindow.__name__ == "LibraryDataWindow"
    assert panel_module.QcPanel.__name__ == "QcPanel"


def test_window_lifecycle_uses_explicit_close_callback() -> None:
    """The child window must not mutate MainScreen private state."""
    window_module = importlib.import_module("src.ui.library_data_window")
    signature = inspect.signature(window_module.LibraryDataWindow)
    source = (Path(__file__).parents[1] / "src" / "ui" / "library_data_window.py").read_text(
        encoding="utf-8"
    )

    assert "on_closed" in signature.parameters
    assert "main._library_data_window" not in source
    assert "_clear_main_reference" not in source


def test_panel_contexts_have_no_dynamic_attribute_escape_hatch() -> None:
    """Composition protocols must declare capabilities without __getattr__."""
    module_dir = Path(__file__).parents[1] / "src" / "ui" / "library_analysis"

    for filename in (
        "contexts.py",
        "qc_panel.py",
        "report_controller.py",
        "rt_assignment_panel.py",
        "pedigree_panel.py",
        "splittree_panel.py",
    ):
        source = (module_dir / filename).read_text(encoding="utf-8")
        assert "def __getattr__" not in source


def test_extracted_class_methods_have_valid_binding_signatures() -> None:
    """Methods must accept their instance unless explicitly declared static."""
    module_dir = Path(__file__).parents[1] / "src" / "ui" / "library_analysis"
    invalid_methods: list[str] = []

    for path in module_dir.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for class_node in (node for node in ast.walk(tree) if isinstance(node, ast.ClassDef)):
            methods = (
                node
                for node in class_node.body
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            )
            for method in methods:
                decorators = {
                    decorator.id
                    for decorator in method.decorator_list
                    if isinstance(decorator, ast.Name)
                }
                first_argument = method.args.args[0].arg if method.args.args else None
                explicitly_bound = bool(decorators.intersection({"staticmethod", "classmethod"}))
                if first_argument not in {"self", "cls"} and not explicitly_bound:
                    invalid_methods.append(f"{path.name}:{class_node.name}.{method.name}")

    assert invalid_methods == []


def test_window_is_composition_root_and_shell_is_extracted() -> None:
    """Bulky shell construction must remain outside the public window module."""
    source_root = Path(__file__).parents[1] / "src" / "ui"
    window_source = (source_root / "library_data_window.py").read_text(encoding="utf-8")
    shell_source = (source_root / "library_analysis" / "window_shell.py").read_text(
        encoding="utf-8"
    )

    assert len(window_source.splitlines()) < 1200
    assert "class WindowShell" in shell_source
    assert "def _build_right_content" in shell_source
    assert "def _build_right_content" not in window_source
    assert "Delegate to the composed" not in window_source


def test_panels_use_explicit_callbacks_for_cross_component_work() -> None:
    """Panels must not reach sibling components through their host context."""
    module_dir = Path(__file__).parents[1] / "src" / "ui" / "library_analysis"

    for filename in (
        "qc_panel.py",
        "report_controller.py",
        "rt_assignment_panel.py",
        "pedigree_panel.py",
        "splittree_panel.py",
    ):
        source = (module_dir / filename).read_text(encoding="utf-8")
        assert "self._context._qc_panel" not in source
        assert "self._context._report_controller" not in source
        assert "self._context._rt_assignment_panel" not in source
        assert "self._context._pedigree_panel" not in source
        assert "self._context._splittree_panel" not in source


def test_composed_modules_call_only_existing_window_methods() -> None:
    """Direct and aliased host calls must remain valid after extraction."""
    window_module = importlib.import_module("src.ui.library_data_window")
    window_methods = set(dir(window_module.LibraryDataWindow))
    module_dir = Path(__file__).parents[1] / "src" / "ui" / "library_analysis"

    missing_calls: dict[str, list[str]] = {}
    for path in module_dir.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        host_calls: set[str] = set()
        functions = (
            node
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        )
        for function in functions:
            aliases: set[str] = set()
            for node in ast.walk(function):
                if not isinstance(node, ast.Assign):
                    continue
                value = node.value
                if (
                    isinstance(value, ast.Attribute)
                    and isinstance(value.value, ast.Name)
                    and value.value.id == "self"
                    and value.attr in {"_context", "_host"}
                ):
                    aliases.update(
                        target.id for target in node.targets if isinstance(target, ast.Name)
                    )
            for node in ast.walk(function):
                if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                    continue
                owner = node.func.value
                direct_host = (
                    isinstance(owner, ast.Attribute)
                    and isinstance(owner.value, ast.Name)
                    and owner.value.id == "self"
                    and owner.attr in {"_context", "_host"}
                )
                aliased_host = isinstance(owner, ast.Name) and owner.id in aliases
                if direct_host or aliased_host:
                    host_calls.add(node.func.attr)
        missing = sorted(host_calls - window_methods)
        if missing:
            missing_calls[path.name] = missing

    assert missing_calls == {}


def test_qc_owns_save_load_controls_and_shell_builds_busy_overlay() -> None:
    """Extracted construction helpers must be owned by the component using them."""
    module_dir = Path(__file__).parents[1] / "src" / "ui" / "library_analysis"
    qc_source = (module_dir / "qc_panel.py").read_text(encoding="utf-8")
    shell_source = (module_dir / "window_shell.py").read_text(encoding="utf-8")

    assert "def _pack_save_load_row" in qc_source
    assert "self._context._pack_save_load_row" not in qc_source
    assert "BusyOverlay(" in shell_source


def test_pedigree_sidebar_owns_summary_and_display_controls() -> None:
    """Pedigree controls stay in the sidebar; export actions live on the tab toolbar."""
    module_dir = Path(__file__).parents[1] / "src" / "ui" / "library_analysis"
    panel_source = (module_dir / "pedigree_panel.py").read_text(encoding="utf-8")
    shell_source = (module_dir / "window_shell.py").read_text(encoding="utf-8")

    assert "def _build_pedigree_display_controls" in panel_source
    assert "self._context._pedigree_frame = ctk.CTkFrame" in panel_source
    assert "self._context._pedigree_export_tree_btn = ctk.CTkButton" not in panel_source
    assert "ped_viz_toolbar" in shell_source
    assert 'text="Export tree PNG…"' in shell_source
    assert 'text="Export pedigree CSV…"' in shell_source
    assert 'fg_color="gray40"' in shell_source
    assert "_pedigree_body_paned" not in shell_source
    assert "_pedigree_left_paned" not in shell_source
    assert "_create_vertical_paned" not in shell_source


def test_splittree_sidebar_separates_data_and_display_controls() -> None:
    """Split-tree sidebar must distinguish data inputs from active plot controls."""
    module_dir = Path(__file__).parents[1] / "src" / "ui" / "library_analysis"
    panel_source = (module_dir / "splittree_panel.py").read_text(encoding="utf-8")

    sidebar_method = panel_source.split(
        "def _build_splittree_viz_sidebar_content", maxsplit=1
    )[1].split("def _add_sidebar_label", maxsplit=1)[0]
    tab_method = panel_source.split("def _build_splittree_tab", maxsplit=1)[1].split(
        "def _build_display_controls", maxsplit=1
    )[0]

    assert 'text="Plot data"' in sidebar_method
    assert 'text="Active plot parameters"' in sidebar_method
    assert "Validate RT column" in sidebar_method
    assert sidebar_method.index('text="Plot data"') < sidebar_method.index(
        'text="Active plot parameters"'
    )
    assert "self._build_display_controls(display_controls)" in sidebar_method
    assert "self._build_display_controls" not in tab_method
    assert "_splittree_body_paned" not in panel_source
    assert "build_tree_figure_host(" in tab_method
    assert 'title="Split-tree"' in tab_method
    assert "subtitle=" not in tab_method
    assert 'text="Export tree PNG…"' in tab_method
    assert 'text="Export all branches…"' in tab_method
    assert 'fg_color="gray40"' in tab_method
    assert "def _on_export_splittree_png" in panel_source
    assert "def _on_export_splittree_branches" in panel_source


def test_window_reveals_only_after_initial_widgets_are_built() -> None:
    """Startup must not expose a partially constructed CustomTkinter window."""
    source = (
        Path(__file__).parents[1] / "src" / "ui" / "library_data_window.py"
    ).read_text(encoding="utf-8")

    assert "self.withdraw()" in source
    assert "self.after_idle(self._finish_initial_display)" in source
    assert "self.deiconify()" in source


def test_pedigree_tab_can_open_before_assignment() -> None:
    """Pedigree visualization should show its empty state without redirecting."""
    source = (
        Path(__file__).parents[1]
        / "src"
        / "ui"
        / "library_analysis"
        / "window_shell.py"
    ).read_text(encoding="utf-8")

    assert "Run pedigree RT assignment first, then open this tab." not in source
    assert "tab == _TAB_PEDIGREE_VIZ and self._host._pedigree_result is None" not in source
