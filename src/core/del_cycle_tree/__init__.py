# src/core/del_cycle_tree/__init__.py
"""
Split-tree (combinatorial BB tree) analysis, visualization, and export.

Product UI name: **Split-tree visualization** / **Export analysis bundle**.
Internal package name ``del_cycle_tree`` is historical; prefer “split-tree” in
user-facing strings and docs.
"""

from src.core.del_cycle_tree.export import (
    DelCycleExportResult,
    export_del_cycle_csv,
    export_del_cycle_package,
)
from src.core.del_cycle_tree.models import DelCycleTreeData, DelCycleTreeView, CompoundRtAssignment
from src.core.del_cycle_tree.render import render_del_cycle_tree_figure
from src.core.del_cycle_tree.service import (
    build_assignments_from_del_cycle_tree,
    build_del_cycle_tree_data,
    build_del_cycle_tree_for_path,
    build_del_cycle_tree_from_metadata_for_path,
    build_del_cycle_tree_from_pedigree,
    build_del_cycle_tree_from_session_cache,
    build_del_cycle_tree_from_session_cache_for_path,
    registered_metadata_column_names,
    resolve_compound_rt_assignments,
    resolve_compound_rt_assignments_for_path,
    validate_registered_metadata_columns,
)

__all__ = [
    "CompoundRtAssignment",
    "DelCycleTreeData",
    "DelCycleTreeView",
    "build_assignments_from_del_cycle_tree",
    "build_del_cycle_tree_data",
    "build_del_cycle_tree_for_path",
    "build_del_cycle_tree_from_metadata_for_path",
    "build_del_cycle_tree_from_pedigree",
    "build_del_cycle_tree_from_session_cache",
    "build_del_cycle_tree_from_session_cache_for_path",
    "registered_metadata_column_names",
    "DelCycleExportResult",
    "export_del_cycle_csv",
    "export_del_cycle_package",
    "resolve_compound_rt_assignments",
    "resolve_compound_rt_assignments_for_path",
    "validate_registered_metadata_columns",
    "render_del_cycle_tree_figure",
]
