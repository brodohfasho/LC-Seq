# src/core/library_metrics_store.py
"""
Save and load Library Data computation snapshots (JSON + plot images).
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
from src.core.library_metrics import (
    ChannelAggregateStats,
    LibraryComputationSnapshot,
    MetricResult,
    PlotResult,
)

logger = logging.getLogger(__name__)

SNAPSHOT_FORMAT_VERSION = "2.0"
LEGACY_SNAPSHOT_FORMAT_VERSION = "1.0"


def get_library_data_dir() -> Path:
    """Ensure ``output/library_data`` exists and return its path."""
    directory = get_application_root() / "output" / "library_data"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def snapshot_plots_dir(json_path: Path) -> Path:
    """Directory beside a snapshot JSON where plot PNG files are stored."""
    return json_path.parent / f"{json_path.stem}_plots"


def session_plots_dir(database_path: Path) -> Path:
    """Working directory for in-session plot PNG files before save."""
    stem = sanitize_database_stem(database_path.stem)
    directory = get_library_data_dir() / ".session" / stem / "plots"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def _channel_stats_to_dict(ch: ChannelAggregateStats) -> Dict[str, Any]:
    return {
        "count_name": ch.count_name,
        "mean": ch.mean,
        "std_dev": ch.std_dev,
        "n": ch.n,
    }


def _channel_stats_from_dict(data: Dict[str, Any]) -> ChannelAggregateStats:
    return ChannelAggregateStats(
        count_name=str(data["count_name"]),
        mean=float(data["mean"]),
        std_dev=float(data["std_dev"]),
        n=int(data["n"]),
    )


def _metric_result_to_dict(metric: MetricResult) -> Dict[str, Any]:
    return {
        "metric_id": metric.metric_id,
        "title": metric.title,
        "help_text": metric.help_text,
        "channels": [_channel_stats_to_dict(ch) for ch in metric.channels],
    }


def _metric_result_from_dict(data: Dict[str, Any]) -> MetricResult:
    return MetricResult(
        metric_id=str(data["metric_id"]),
        title=str(data["title"]),
        help_text=str(data["help_text"]),
        channels=[_channel_stats_from_dict(ch) for ch in data.get("channels", [])],
    )


def _plot_result_to_dict(plot: PlotResult) -> Dict[str, Any]:
    filename = plot.image_path.name if plot.image_path is not None else ""
    return {
        "plot_id": plot.plot_id,
        "title": plot.title,
        "help_text": plot.help_text,
        "channel": plot.channel,
        "image_filename": filename,
    }


def _plot_result_from_dict(data: Dict[str, Any], plots_dir: Optional[Path]) -> PlotResult:
    filename = str(data.get("image_filename", "")).strip()
    image_path: Optional[Path] = None
    if filename and plots_dir is not None:
        candidate = plots_dir / filename
        if candidate.is_file():
            image_path = candidate
    return PlotResult(
        plot_id=str(data.get("plot_id", "")),
        title=str(data.get("title", filename)),
        help_text=str(data.get("help_text", "")),
        channel=str(data.get("channel", "")),
        image_path=image_path,
    )


def snapshot_to_dict(snapshot: LibraryComputationSnapshot) -> Dict[str, Any]:
    """Serialize a computation snapshot for JSON storage."""
    processed_at = snapshot.processed_at
    if processed_at.tzinfo is None:
        processed_at = processed_at.replace(tzinfo=timezone.utc)
    return {
        "format_version": SNAPSHOT_FORMAT_VERSION,
        "processed_at": processed_at.astimezone(timezone.utc).isoformat(),
        "database_path": snapshot.database_path,
        "database_kind": snapshot.database_kind,
        "fraction_count": snapshot.fraction_count,
        "selected_channels": list(snapshot.selected_channels),
        "selected_metrics": list(snapshot.selected_metrics),
        "selected_plots": list(snapshot.selected_plots),
        "entries_attempted": snapshot.entries_attempted,
        "entries_used": snapshot.entries_used,
        "entries_skipped": snapshot.entries_skipped,
        "metric_results": [_metric_result_to_dict(m) for m in snapshot.metric_results],
        "plot_results": [_plot_result_to_dict(p) for p in snapshot.plot_results],
    }


def snapshot_from_dict(data: Dict[str, Any], json_path: Optional[Path] = None) -> LibraryComputationSnapshot:
    """Deserialize a computation snapshot from JSON."""
    processed_raw = data.get("processed_at")
    if not processed_raw:
        processed_at = datetime.now(timezone.utc)
    else:
        processed_at = datetime.fromisoformat(str(processed_raw))
        if processed_at.tzinfo is None:
            processed_at = processed_at.replace(tzinfo=timezone.utc)

    plots_dir = snapshot_plots_dir(json_path) if json_path is not None else None
    plot_results = [
        _plot_result_from_dict(item, plots_dir)
        for item in data.get("plot_results", [])
        if isinstance(item, dict)
    ]

    return LibraryComputationSnapshot(
        processed_at=processed_at,
        database_path=str(data["database_path"]),
        database_kind=str(data.get("database_kind", "full")),
        fraction_count=int(data.get("fraction_count", 96)),
        selected_channels=[str(ch) for ch in data.get("selected_channels", [])],
        selected_metrics=[str(m) for m in data.get("selected_metrics", [])],
        selected_plots=[str(p) for p in data.get("selected_plots", [])],
        entries_attempted=int(data.get("entries_attempted", 0)),
        entries_used=int(data.get("entries_used", 0)),
        entries_skipped=int(data.get("entries_skipped", 0)),
        metric_results=[
            _metric_result_from_dict(item) for item in data.get("metric_results", [])
        ],
        plot_results=plot_results,
    )


def build_snapshot_filename(database_path: Path, processed_at: datetime) -> str:
    """Build ``{db_stem}_{YYYYMMDD_HHMMSS}.json`` for a snapshot."""
    stem = sanitize_database_stem(database_path.stem)
    if processed_at.tzinfo is None:
        processed_at = processed_at.replace(tzinfo=timezone.utc)
    local = processed_at.astimezone()
    stamp = local.strftime("%Y%m%d_%H%M%S")
    return f"{stem}_{stamp}.json"


def allocate_snapshot_path(
    database_path: Path,
    processed_at: Optional[datetime] = None,
) -> Path:
    """Return a unique path under ``output/library_data`` for a new snapshot."""
    when = processed_at or datetime.now(timezone.utc)
    directory = get_library_data_dir()
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


def save_snapshot(
    snapshot: LibraryComputationSnapshot,
    path: Optional[Path] = None,
    *,
    plot_source_dir: Optional[Path] = None,
) -> Path:
    """
    Write a computation snapshot to disk and copy plot PNG files beside it.

    Args:
        snapshot: Result to persist.
        path: Target JSON file; when omitted, auto-allocates under ``output/library_data``.
        plot_source_dir: Directory containing session plot PNG files to copy.

    Returns:
        Path to the JSON file written.
    """
    target = path or allocate_snapshot_path(Path(snapshot.database_path), snapshot.processed_at)
    target.parent.mkdir(parents=True, exist_ok=True)
    plots_dir = snapshot_plots_dir(target)
    plots_dir.mkdir(parents=True, exist_ok=True)

    updated_plots: List[PlotResult] = []
    for plot in snapshot.plot_results:
        src = plot.image_path
        if src is None and plot_source_dir is not None:
            src = plot_source_dir / f"{plot.plot_id}_{plot.channel}.png"
        if src is None or not src.is_file():
            if plot_source_dir is not None:
                matches = list(plot_source_dir.glob(f"{plot.plot_id}_*.png"))
                src = matches[0] if matches else None
        if src is None or not src.is_file():
            continue
        dest = plots_dir / src.name
        if src.resolve() != dest.resolve():
            shutil.copy2(src, dest)
        updated_plots.append(
            PlotResult(
                plot_id=plot.plot_id,
                title=plot.title,
                help_text=plot.help_text,
                channel=plot.channel,
                image_path=dest,
            )
        )

    if plot_source_dir is not None and plot_source_dir.is_dir() and not updated_plots:
        for src in sorted(plot_source_dir.glob("*.png")):
            dest = plots_dir / src.name
            shutil.copy2(src, dest)
            stem = src.stem
            parts = stem.split("_", 1)
            updated_plots.append(
                PlotResult(
                    plot_id=parts[0] if parts else stem,
                    title=stem.replace("_", " "),
                    help_text="",
                    channel=parts[1] if len(parts) > 1 else "",
                    image_path=dest,
                )
            )

    snapshot.plot_results = updated_plots
    payload = snapshot_to_dict(snapshot)
    with open(target, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)
    logger.info("Saved library data snapshot: %s", target)
    return target


def load_snapshot(path: Path) -> LibraryComputationSnapshot:
    """Load a computation snapshot from a JSON file."""
    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)
    version = str(data.get("format_version", ""))
    if version not in (SNAPSHOT_FORMAT_VERSION, LEGACY_SNAPSHOT_FORMAT_VERSION):
        logger.warning(
            "Library snapshot format version %s (expected %s): %s",
            version,
            SNAPSHOT_FORMAT_VERSION,
            path,
        )
    return snapshot_from_dict(data, json_path=path)


def list_snapshots(
    *,
    database_path: Optional[Path] = None,
    newest_first: bool = True,
) -> List[Path]:
    """List snapshot JSON files, optionally filtered to one database stem prefix."""
    directory = get_library_data_dir()
    if not directory.is_dir():
        return []

    prefix: Optional[str] = None
    if database_path is not None:
        prefix = f"{sanitize_database_stem(database_path.stem)}_"

    paths = [p for p in directory.glob("*.json") if p.is_file()]
    if prefix:
        paths = [p for p in paths if p.name.startswith(prefix)]

    paths.sort(key=lambda p: p.stat().st_mtime, reverse=newest_first)
    return paths


def get_latest_snapshot_path(database_path: Path) -> Optional[Path]:
    """Return the newest saved snapshot for a database, if any."""
    matches = list_snapshots(database_path=database_path, newest_first=True)
    return matches[0] if matches else None


def database_paths_match(saved_path: str, active_path: Path) -> bool:
    """True when two database paths refer to the same file."""
    try:
        return Path(saved_path).resolve() == active_path.resolve()
    except OSError:
        return False
