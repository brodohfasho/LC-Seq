# src/core/pedigree_analysis_store.py
"""
Save and load pedigree analysis snapshots (JSON + tree PNG).
"""

from __future__ import annotations

import json
import logging
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.core.app_paths import get_application_root
from src.core.database_library import sanitize_database_stem
from src.core.library_metrics_store import database_paths_match
from src.models.analysis_settings import AnalysisSettings
from src.models.pedigree_result import (
    EntryProductProminence,
    PedigreeAnalysisResult,
    PedigreeNodeRecord,
    PedigreeTierSummary,
    ProductProminenceSummary,
)

logger = logging.getLogger(__name__)

SNAPSHOT_FORMAT_VERSION = "1.0"


def get_pedigree_analysis_dir() -> Path:
    """Ensure ``output/pedigree_analysis`` exists and return its path."""
    directory = get_application_root() / "output" / "pedigree_analysis"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def session_pedigree_dir(database_path: Path) -> Path:
    """Working directory for in-session pedigree artifacts before save."""
    stem = sanitize_database_stem(database_path.stem)
    directory = get_pedigree_analysis_dir() / ".session" / stem
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def snapshot_tree_path(json_path: Path) -> Path:
    """Tree PNG path beside a pedigree snapshot JSON file."""
    return json_path.with_name(f"{json_path.stem}_tree.png")


def _node_to_dict(record: PedigreeNodeRecord) -> Dict[str, Any]:
    return {
        "id": record.id,
        "label": record.label,
        "tier": record.tier,
        "kind": record.kind,
        "members": list(record.members),
        "parent_ids": list(record.parent_ids),
        "evaluated": record.evaluated,
        "passed": record.passed,
        "insufficient_data": record.insufficient_data,
        "effective_threshold": record.effective_threshold,
        "score_test_rt": record.score_test_rt,
        "score_test_rt_se": record.score_test_rt_se,
        "score_test_p_value": record.score_test_p_value,
        "bayesian_pick": record.bayesian_pick,
        "bayesian_pick_posterior": record.bayesian_pick_posterior,
        "n_replicates": record.n_replicates,
        "n_replicates_with_signal": record.n_replicates_with_signal,
        "initial_most_significant_picks": list(record.initial_most_significant_picks),
    }


def _node_from_dict(data: Dict[str, Any]) -> PedigreeNodeRecord:
    return PedigreeNodeRecord(
        id=str(data["id"]),
        label=str(data.get("label", "")),
        tier=int(data.get("tier", 0)),
        kind=str(data.get("kind", "class")),
        members=[str(m) for m in data.get("members", [])],
        parent_ids=[str(p) for p in data.get("parent_ids", [])],
        evaluated=bool(data.get("evaluated", False)),
        passed=bool(data.get("passed", False)),
        insufficient_data=bool(data.get("insufficient_data", False)),
        effective_threshold=_optional_float(data.get("effective_threshold")),
        score_test_rt=_optional_float(data.get("score_test_rt")),
        score_test_rt_se=_optional_float(data.get("score_test_rt_se")),
        score_test_p_value=_optional_float(data.get("score_test_p_value")),
        bayesian_pick=_optional_float(data.get("bayesian_pick")),
        bayesian_pick_posterior=_optional_float(data.get("bayesian_pick_posterior")),
        n_replicates=int(data.get("n_replicates", 0)),
        n_replicates_with_signal=int(data.get("n_replicates_with_signal", 0)),
        initial_most_significant_picks=[
            float(x) for x in data.get("initial_most_significant_picks", []) if x is not None
        ],
    )


def _optional_float(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _tier_summary_to_dict(summary: PedigreeTierSummary) -> Dict[str, Any]:
    return {
        "tier": summary.tier,
        "pass_count": summary.pass_count,
        "fail_count": summary.fail_count,
        "pruned_count": summary.pruned_count,
    }


def _tier_summary_from_dict(data: Dict[str, Any]) -> PedigreeTierSummary:
    return PedigreeTierSummary(
        tier=int(data["tier"]),
        pass_count=int(data.get("pass_count", 0)),
        fail_count=int(data.get("fail_count", 0)),
        pruned_count=int(data.get("pruned_count", 0)),
    )


def _entry_prominence_to_dict(entry: EntryProductProminence) -> Dict[str, Any]:
    return {
        "compound_id": entry.compound_id,
        "node_id": entry.node_id,
        "chosen_rt": entry.chosen_rt,
        "prominence": entry.prominence,
        "passed": entry.passed,
    }


def _entry_prominence_from_dict(data: Dict[str, Any]) -> EntryProductProminence:
    return EntryProductProminence(
        compound_id=str(data["compound_id"]),
        node_id=str(data["node_id"]),
        chosen_rt=float(data["chosen_rt"]),
        prominence=float(data["prominence"]),
        passed=bool(data.get("passed", True)),
    )


def _product_prominence_to_dict(summary: ProductProminenceSummary) -> Dict[str, Any]:
    return {
        "channel": summary.channel,
        "mean": summary.mean,
        "std_dev": summary.std_dev,
        "n_pass_with_prominence": summary.n_pass_with_prominence,
        "n_compound_nodes": summary.n_compound_nodes,
        "n_skipped": summary.n_skipped,
        "entries": [_entry_prominence_to_dict(e) for e in summary.entries],
    }


def _product_prominence_from_dict(data: Dict[str, Any]) -> ProductProminenceSummary:
    entries = [
        _entry_prominence_from_dict(item)
        for item in data.get("entries", [])
        if isinstance(item, dict)
    ]
    return ProductProminenceSummary(
        channel=str(data.get("channel", "")),
        mean=float(data.get("mean", 0.0)),
        std_dev=float(data.get("std_dev", 0.0)),
        n_pass_with_prominence=int(data.get("n_pass_with_prominence", 0)),
        n_compound_nodes=int(data.get("n_compound_nodes", 0)),
        n_skipped=int(data.get("n_skipped", 0)),
        entries=entries,
    )


def result_to_dict(result: PedigreeAnalysisResult) -> Dict[str, Any]:
    """Serialize a pedigree result for JSON storage."""
    computed_at = result.computed_at
    if computed_at.tzinfo is None:
        computed_at = computed_at.replace(tzinfo=timezone.utc)
    settings = result.settings
    variants = settings.selected_variants
    payload: Dict[str, Any] = {
        "format_version": SNAPSHOT_FORMAT_VERSION,
        "computed_at": computed_at.astimezone(timezone.utc).isoformat(),
        "database_path": result.database_path,
        "channel": result.channel,
        "null_token": result.null_token,
        "library_cycle_count": result.library_cycle_count,
        "max_display_tier": result.max_display_tier,
        "isoform_label": result.isoform_label,
        "backend_name": result.backend_name,
        "n_compounds_loaded": result.n_compounds_loaded,
        "n_chromatograms": result.n_chromatograms,
        "settings": {
            "count_channel": settings.count_channel,
            "time_unit": settings.time_unit,
            "alpha": settings.alpha,
            "tolerance": settings.tolerance,
            "selected_variants": list(variants) if variants is not None else None,
        },
        "tier_summaries": [_tier_summary_to_dict(s) for s in result.tier_summaries],
        "records": [_node_to_dict(r) for r in result.records],
        "tree_image_filename": (
            result.tree_image_path.name if result.tree_image_path is not None else ""
        ),
        "tree_render_engine": result.tree_render_engine or "",
        "tree_render_note": result.tree_render_note or "",
    }
    if result.product_prominence is not None:
        payload["product_prominence"] = _product_prominence_to_dict(result.product_prominence)
    return payload


def result_from_dict(data: Dict[str, Any], json_path: Optional[Path] = None) -> PedigreeAnalysisResult:
    """Deserialize a pedigree result from JSON."""
    computed_raw = data.get("computed_at")
    if not computed_raw:
        computed_at = datetime.now(timezone.utc)
    else:
        computed_at = datetime.fromisoformat(str(computed_raw))
        if computed_at.tzinfo is None:
            computed_at = computed_at.replace(tzinfo=timezone.utc)

    settings_data = data.get("settings") or {}
    variants = settings_data.get("selected_variants")
    settings = AnalysisSettings(
        count_channel=str(settings_data.get("count_channel", data.get("channel", ""))),
        time_unit=settings_data.get("time_unit", "seconds"),
        alpha=float(settings_data.get("alpha", 1e-3)),
        tolerance=float(settings_data.get("tolerance", 30.0)),
        selected_variants=list(variants) if variants is not None else None,
    )

    tree_path: Optional[Path] = None
    tree_name = str(data.get("tree_image_filename", "")).strip()
    if tree_name and json_path is not None:
        candidate = json_path.parent / tree_name
        if candidate.is_file():
            tree_path = candidate
        else:
            alt = snapshot_tree_path(json_path)
            if alt.is_file():
                tree_path = alt

    product_prominence: Optional[ProductProminenceSummary] = None
    prom_data = data.get("product_prominence")
    if isinstance(prom_data, dict):
        product_prominence = _product_prominence_from_dict(prom_data)

    return PedigreeAnalysisResult(
        database_path=str(data["database_path"]),
        channel=str(data["channel"]),
        settings=settings,
        null_token=str(data.get("null_token", "AgxNull")),
        library_cycle_count=int(data.get("library_cycle_count", 0)),
        records=[_node_from_dict(item) for item in data.get("records", []) if isinstance(item, dict)],
        tier_summaries=[
            _tier_summary_from_dict(item)
            for item in data.get("tier_summaries", [])
            if isinstance(item, dict)
        ],
        backend_name=str(data.get("backend_name", "")),
        computed_at=computed_at,
        n_compounds_loaded=int(data.get("n_compounds_loaded", 0)),
        n_chromatograms=int(data.get("n_chromatograms", 0)),
        max_display_tier=(
            int(data["max_display_tier"])
            if data.get("max_display_tier") is not None
            else None
        ),
        isoform_label=str(data.get("isoform_label", "All")),
        tree_image_path=tree_path,
        tree_render_engine=str(data.get("tree_render_engine", "")) or None,
        tree_render_note=str(data.get("tree_render_note", "")) or None,
        product_prominence=product_prominence,
    )


def build_snapshot_filename(database_path: Path, computed_at: datetime) -> str:
    """Build ``{db_stem}_pedigree_{YYYYMMDD_HHMMSS}.json``."""
    stem = sanitize_database_stem(database_path.stem)
    if computed_at.tzinfo is None:
        computed_at = computed_at.replace(tzinfo=timezone.utc)
    stamp = computed_at.astimezone().strftime("%Y%m%d_%H%M%S")
    return f"{stem}_pedigree_{stamp}.json"


def allocate_snapshot_path(
    database_path: Path,
    computed_at: Optional[datetime] = None,
) -> Path:
    """Return a unique path under ``output/pedigree_analysis`` for a new snapshot."""
    when = computed_at or datetime.now(timezone.utc)
    directory = get_pedigree_analysis_dir()
    base_name = build_snapshot_filename(database_path, when).removesuffix(".json")
    candidate = directory / f"{base_name}.json"
    if not candidate.is_file():
        return candidate
    n = 2
    while True:
        alt = directory / f"{base_name}_{n}.json"
        if not alt.is_file():
            return alt
        n += 1


def save_pedigree_result(
    result: PedigreeAnalysisResult,
    path: Optional[Path] = None,
    *,
    tree_source: Optional[Path] = None,
) -> Path:
    """
    Write a pedigree snapshot JSON and copy the tree PNG beside it.

    Returns:
        Path to the JSON file written.
    """
    target = path or allocate_snapshot_path(Path(result.database_path), result.computed_at)
    target.parent.mkdir(parents=True, exist_ok=True)

    tree_dest = snapshot_tree_path(target)
    src = tree_source or result.tree_image_path
    if src is not None and Path(src).is_file():
        if Path(src).resolve() != tree_dest.resolve():
            shutil.copy2(src, tree_dest)
        result.tree_image_path = tree_dest

    payload = result_to_dict(result)
    payload["tree_image_filename"] = tree_dest.name if tree_dest.is_file() else ""
    with open(target, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)
    logger.info("Saved pedigree analysis snapshot: %s", target)
    return target


def load_pedigree_result(path: Path) -> PedigreeAnalysisResult:
    """Load a pedigree snapshot from a JSON file."""
    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)
    version = str(data.get("format_version", ""))
    if version != SNAPSHOT_FORMAT_VERSION:
        logger.warning(
            "Pedigree snapshot format version %s (expected %s): %s",
            version,
            SNAPSHOT_FORMAT_VERSION,
            path,
        )
    return result_from_dict(data, json_path=path)


def list_pedigree_snapshots(
    *,
    database_path: Optional[Path] = None,
    newest_first: bool = True,
) -> List[Path]:
    """List pedigree snapshot JSON files, optionally filtered by database stem."""
    directory = get_pedigree_analysis_dir()
    if not directory.is_dir():
        return []

    prefix: Optional[str] = None
    if database_path is not None:
        prefix = f"{sanitize_database_stem(database_path.stem)}_pedigree_"

    paths = [p for p in directory.glob("*.json") if p.is_file()]
    if prefix:
        paths = [p for p in paths if p.name.startswith(prefix)]

    paths.sort(key=lambda p: p.stat().st_mtime, reverse=newest_first)
    return paths


def get_latest_pedigree_snapshot_path(database_path: Path) -> Optional[Path]:
    """Return the newest saved pedigree snapshot for a database, if any."""
    matches = list_pedigree_snapshots(database_path=database_path, newest_first=True)
    return matches[0] if matches else None
