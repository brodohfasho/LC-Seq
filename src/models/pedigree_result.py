# src/models/pedigree_result.py
"""Domain models for pedigree and lineage analysis results."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
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
class PedigreeTierSummary:
    """Pass / fail / pruned counts for one pedigree tier."""

    tier: int
    pass_count: int
    fail_count: int
    pruned_count: int


@dataclass(frozen=True)
class EntryProductProminence:
    """Product-peak prominence for one full compound node."""

    compound_id: str
    node_id: str
    chosen_rt: float
    prominence: float
    passed: bool


@dataclass(frozen=True)
class ProductProminenceSummary:
    """Library aggregate of pedigree-validated product prominences."""

    channel: str
    mean: float
    std_dev: float
    n_pass_with_prominence: int
    n_compound_nodes: int
    n_skipped: int
    entries: List[EntryProductProminence] = field(default_factory=list)

    @property
    def n_pass(self) -> int:
        return self.n_pass_with_prominence


@dataclass
class PedigreeAnalysisResult:
    """Full-library pedigree evaluation result."""

    database_path: str
    channel: str
    settings: AnalysisSettings
    null_token: str
    library_cycle_count: int
    records: List[PedigreeNodeRecord]
    tier_summaries: List[PedigreeTierSummary]
    backend_name: str
    computed_at: datetime
    n_compounds_loaded: int
    n_chromatograms: int
    max_display_tier: Optional[int] = None
    isoform_label: str = "All"
    tree_image_path: Optional[Path] = None
    tree_render_engine: Optional[str] = None
    tree_render_note: Optional[str] = None
    product_prominence: Optional[ProductProminenceSummary] = None


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


@dataclass(frozen=True)
class LineageBatchResult:
    """Lineage analysis for one or more plotted compounds."""

    results: Tuple[LineageAnalysisResult, ...] = ()
    failed: Tuple[Tuple[str, str], ...] = ()  # (compound_id, error message)

    @property
    def success_count(self) -> int:
        return len(self.results)

    @property
    def failure_count(self) -> int:
        return len(self.failed)

    def result_for(self, compound_id: str) -> Optional[LineageAnalysisResult]:
        key = str(compound_id).strip()
        for result in self.results:
            if str(result.compound_id).strip() == key:
                return result
        return None
