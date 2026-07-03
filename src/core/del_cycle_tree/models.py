# src/core/del_cycle_tree/models.py
"""Data models for DEL-cycle split-tree analysis."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple


class DelCycleTreeView(str, Enum):
    """Which DEL-cycle tree figure to display."""

    FULL = "full"
    BRANCH = "branch"


@dataclass(frozen=True)
class DelCycleRow:
    """One compound row with coupling-order BB positions and retention time."""

    positions: Tuple[str, ...]
    rt: float


@dataclass(frozen=True)
class VerifiedSequence:
    """RT verification outcome for one full product sequence."""

    positions: Tuple[str, ...]
    rt: float
    success: bool


@dataclass(frozen=True)
class DelCycleRtResolution:
    """How retention times were resolved for DEL-cycle tree rows."""

    rt_source: str
    peak_picking_algorithm: str
    n_rt_from_pedigree: int = 0
    n_rt_from_peak_pick: int = 0
    n_rt_from_metadata: int = 0


@dataclass
class DelCycleTreeData:
    """Analyzed DEL-cycle tree ready for rendering."""

    library_cycle_count: int
    null_token: str
    rt_threshold: float
    tree: Dict[str, Any]
    pruned_tree: Dict[str, Any]
    verified_sequences: Dict[Tuple[str, ...], VerifiedSequence]
    full_null_rt: Optional[float]
    bb_index_by_level: List[Dict[str, int]] = field(default_factory=list)
    bb_index_global: Dict[str, int] = field(default_factory=dict)
    truncation_library: Dict[Tuple[str, ...], List[Tuple[Tuple[str, ...], float]]] = field(
        default_factory=dict
    )
    bb1_names: List[str] = field(default_factory=list)
    n_rows: int = 0
    n_verified: int = 0
    rt_source: str = "pedigree"
    peak_picking_algorithm: str = ""
    n_rt_from_pedigree: int = 0
    n_rt_from_peak_pick: int = 0
    n_rt_from_metadata: int = 0
    n_rt_verified_pedigree_agree: int = 0
    pedigree_passed_by_product: Dict[Tuple[str, ...], bool] = field(default_factory=dict)
    pedigree_pruned_tree: Dict[str, Any] = field(default_factory=dict)
    n_pedigree_passed: int = 0
