# src/core/lineage_cache.py
"""
Session cache for lineage analysis library scans and pedigree evaluation.

The first lineage run on a database parses every compound row (slow for large
index libraries). Subsequent runs in the same visualizer session reuse the
loaded compounds and full-library pedigree evaluation when settings match.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Tuple

from src.core.data_store import DataStore
from src.core.pedigree_adapter import (
    ChromatogramKey,
    build_chromatogram_map,
    filter_compounds_by_variant,
    infer_bbs_per_position,
    truncate_positions_from_metadata,
)
from src.core.pedigree_backend import get_pedigree_backend
from src.models.analysis_settings import AnalysisSettings
from src.models.compound import Compound
from src.models.pedigree_result import PedigreeNodeRecord
from src.models.spreadsheet_config import SpreadsheetConfig

ProgressCallback = Callable[[int, int, str], None]
ChromatogramMap = Dict[ChromatogramKey, Tuple[Any, Any]]


def config_fingerprint(config: SpreadsheetConfig) -> str:
    """Stable hash of spreadsheet fields that affect lineage loading."""
    payload = {
        "null_token": config.null_token,
        "library_cycle_count": config.library_cycle_count,
        "bb_position_columns": list(config.bb_position_columns or []),
        "chromatographic_data_column": config.chromatographic_data_column,
        "delimiters": list(config.delimiters or []),
        "time_column_index": config.time_column_index,
        "count_column_indices": list(config.count_column_indices or []),
        "count_names": list(config.count_names or []),
        "analysis_time_unit": config.analysis_time_unit,
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def pedigree_settings_key(settings: AnalysisSettings) -> Tuple[str, ...]:
    """Tuple key for pedigree evaluation inputs."""
    variants = tuple(sorted(str(v) for v in (settings.selected_variants or [])))
    return (
        settings.count_channel,
        settings.time_unit,
        float(settings.tolerance),
        float(settings.alpha),
        variants,
    )


@dataclass
class CachedPedigreeEvaluation:
    """Full-library pedigree state reused across compounds."""

    chromatogram_map: ChromatogramMap
    records_by_id: Dict[str, PedigreeNodeRecord]
    bbs_per_position: List[List[str]]
    filtered_count: int


class LineageSessionCache:
    """
    Per-visualizer-session cache for lineage analysis.

    Invalidate when the active database or spreadsheet pedigree configuration
    changes.
    """

    def __init__(self) -> None:
        self._db_path: Optional[str] = None
        self._config_key: Optional[str] = None
        self._index_database: bool = False
        self._compounds: Optional[List[Compound]] = None
        self._pedigree_key: Optional[Tuple[str, ...]] = None
        self._pedigree: Optional[CachedPedigreeEvaluation] = None

    def invalidate(self) -> None:
        """Drop all cached library and pedigree state."""
        self._db_path = None
        self._config_key = None
        self._index_database = False
        self._compounds = None
        self._pedigree_key = None
        self._pedigree = None

    def _library_matches(self, db_path: str, config_key: str) -> bool:
        return (
            self._compounds is not None
            and self._db_path == db_path
            and self._config_key == config_key
        )

    def get_or_load_compounds(
        self,
        store: DataStore,
        config: SpreadsheetConfig,
        *,
        index_database: bool,
        progress_callback: Optional[ProgressCallback] = None,
    ) -> List[Compound]:
        """Return hydrated compounds, loading from SQLite only on first use."""
        db_path = str(store.db_path.resolve())
        cfg_key = config_fingerprint(config)
        if self._library_matches(db_path, cfg_key):
            if progress_callback is not None:
                progress_callback(
                    0,
                    4,
                    f"Using cached library scan ({len(self._compounds):,} compounds)…",
                )
            return self._compounds

        from src.core.lineage_service import load_all_compounds

        compounds = load_all_compounds(
            store,
            config,
            index_database=index_database,
            progress_callback=progress_callback,
        )
        self._db_path = db_path
        self._config_key = cfg_key
        self._index_database = index_database
        self._compounds = compounds
        self._pedigree_key = None
        self._pedigree = None
        return compounds

    def get_or_evaluate_pedigree(
        self,
        compounds: List[Compound],
        config: SpreadsheetConfig,
        settings: AnalysisSettings,
        *,
        progress_callback: Optional[ProgressCallback] = None,
    ) -> CachedPedigreeEvaluation:
        """Return chromatogram map and pedigree records, reusing when possible."""
        ped_key = pedigree_settings_key(settings)
        if self._pedigree is not None and self._pedigree_key == ped_key:
            if progress_callback is not None:
                progress_callback(
                    2,
                    4,
                    f"Using cached pedigree evaluation ({self._pedigree.filtered_count:,} compounds)…",
                )
            return self._pedigree

        if progress_callback is not None:
            progress_callback(1, 4, "Building chromatogram map…")

        filtered = filter_compounds_by_variant(compounds, settings.selected_variants)
        chromatogram_map = build_chromatogram_map(
            filtered,
            settings.count_channel,
            config,
            time_unit=settings.time_unit,
        )
        if not chromatogram_map:
            with_bb = sum(
                1
                for c in filtered
                if truncate_positions_from_metadata(c, config) is not None
            )
            with_data = sum(1 for c in filtered if c.data_points)
            raise ValueError(
                f"No chromatograms found for channel {settings.count_channel!r}. "
                f"Loaded {len(filtered)} compound(s) ({with_bb} with BB metadata, "
                f"{with_data} with parsed chromatogram data)."
            )

        if progress_callback is not None:
            progress_callback(2, 4, "Running pedigree evaluation…")

        backend = get_pedigree_backend()
        bbs_per_position = infer_bbs_per_position(filtered, config)
        records = backend.evaluate_library(
            bbs_per_position,
            config.null_token,
            chromatogram_map,
            settings.tolerance,
            settings.alpha,
            min_prominence=settings.min_prominence,
            min_pct_area=settings.min_pct_area,
            settings=settings,
        )
        records_by_id: Dict[str, PedigreeNodeRecord] = {r.id: r for r in records}
        cached = CachedPedigreeEvaluation(
            chromatogram_map=chromatogram_map,
            records_by_id=records_by_id,
            bbs_per_position=bbs_per_position,
            filtered_count=len(filtered),
        )
        self._pedigree_key = ped_key
        self._pedigree = cached
        return cached
