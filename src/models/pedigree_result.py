# src/models/pedigree_result.py
"""Domain models for pedigree and lineage analysis results."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from src.models.analysis_settings import AnalysisSettings


@dataclass(frozen=True)
class PedigreeNodeRecord:
    """One evaluated pedigree node (mirrors Rust ``NodeRecord``)."""

    id: str
    label: str
    tier: int
    kind: str
    members: List[str] = field(default_factory=list)
    parent_ids: List[str] = field(default_factory=list)
    evaluated: bool = False
    passed: bool = False
    insufficient_data: bool = False
    effective_threshold: Optional[float] = None
    score_test_rt: Optional[float] = None
    score_test_rt_se: Optional[float] = None
    score_test_p_value: Optional[float] = None
    bayesian_pick: Optional[float] = None
    bayesian_pick_posterior: Optional[float] = None
    n_replicates: int = 0
    n_replicates_with_signal: int = 0
    initial_most_significant_picks: List[float] = field(default_factory=list)


@dataclass(frozen=True)
class LineagePanel:
    """One stacked tier panel in a lineage figure."""

    class_bbs: List[str]
    tier: int
    n_replicates: int
    effective_threshold: float
    record: PedigreeNodeRecord


@dataclass(frozen=True)
class LineageAnalysisResult:
    """Full lineage analysis for one compound."""

    compound_id: str
    leaf_class_bbs: List[str]
    channel: str
    settings: AnalysisSettings
    panels: List[LineagePanel]
    records_by_id: Dict[str, PedigreeNodeRecord]
    backend_name: str
    computed_at: datetime
    chromatogram_map: Dict[Tuple[str, ...], Tuple[Any, Any]] = field(default_factory=dict)
