# src/core/library_metrics_store.py
"""
Save and load Library Data computation snapshots (JSON + plot images).
"""

from __future__ import annotations

import json
import logging
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from src.core.app_paths import get_application_root
from src.core.database_library import sanitize_database_stem
from src.core.library_metrics import (
    ChannelAggregateStats,
    LibraryComputationSnapshot,
    MetricResult,
    PlotResult,
)
from src.core.library_signal_quality import (
    DEFAULT_SIGNAL_QUALITY_ALPHA,
    SignalQualityComputeOptions,
)

if TYPE_CHECKING:
    from src.core.library_metrics import LibraryScanData
    from src.models.spreadsheet_config import SpreadsheetConfig

logger = logging.getLogger(__name__)

SNAPSHOT_FORMAT_VERSION = "2.1"
LEGACY_SNAPSHOT_FORMAT_VERSION = "1.0"


def _signal_quality_options_to_dict(
    options: SignalQualityComputeOptions,
) -> Dict[str, Any]:
    return {
        "peak_picking_algorithm": options.peak_picking_algorithm,
        "alpha": options.alpha,
        "time_unit": options.time_unit,
        "min_prominence": options.min_prominence,
        "min_pct_area": options.min_pct_area,
        "gaussian_min_height_factor": options.gaussian_min_height_factor,
        "gaussian_fit_width": options.gaussian_fit_width,
        "gaussian_stddev_threshold": options.gaussian_stddev_threshold,
        "gaussian_minimum_rt": options.gaussian_minimum_rt,
    }


def _signal_quality_options_from_dict(
    data: Optional[Dict[str, Any]],
    *,
    legacy_alpha: float = DEFAULT_SIGNAL_QUALITY_ALPHA,
) -> SignalQualityComputeOptions:
    if not data:
        return SignalQualityComputeOptions(alpha=legacy_alpha)
    return SignalQualityComputeOptions(
        peak_picking_algorithm=str(data.get("peak_picking_algorithm", "modern")),
        alpha=float(data.get("alpha", legacy_alpha)),
        time_unit=str(data.get("time_unit", "seconds")),  # type: ignore[arg-type]
        min_prominence=float(data.get("min_prominence", 0.0)),
        min_pct_area=float(data.get("min_pct_area", 0.0)),
        gaussian_min_height_factor=float(
            data.get("gaussian_min_height_factor", 0.35)
        ),
        gaussian_fit_width=float(data.get("gaussian_fit_width", 30.0)),
        gaussian_stddev_threshold=float(data.get("gaussian_stddev_threshold", 2.0)),
        gaussian_minimum_rt=float(data.get("gaussian_minimum_rt", 600.0)),
    )


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


def session_scan_path(database_path: Path) -> Path:
    """Pickle path for the in-session library scan cache."""
    stem = sanitize_database_stem(database_path.stem)
    directory = get_library_data_dir() / ".session" / stem
    directory.mkdir(parents=True, exist_ok=True)
    return directory / "scan.pkl"


def stamp_scan_provenance(scan: "LibraryScanData", database_path: Path) -> None:
    """Record which database produced a scan (for export/import validation)."""
    scan.source_database_name = database_path.name
    if scan.scanned_at is None:
        scan.scanned_at = datetime.now(timezone.utc)


def save_session_scan(scan: "LibraryScanData", database_path: Path) -> List[Path]:
    """
    Persist the parsed library scan for reuse within and across sessions.

    Only one session scan pickle is retained: caches for other databases are
    deleted before writing this one.

    Returns:
        Paths of other-database scan pickles that were removed.
    """
    import pickle

    stamp_scan_provenance(scan, database_path)
    removed = delete_other_session_scans(database_path)
    path = session_scan_path(database_path)
    try:
        with path.open("wb") as handle:
            pickle.dump(scan, handle, protocol=pickle.HIGHEST_PROTOCOL)
        logger.info("Saved session library scan to %s", path)
    except OSError as exc:
        logger.warning("Could not save session library scan: %s", exc)
    return removed


def delete_session_scan(database_path: Path) -> bool:
    """Remove the persisted session scan pickle for a database, if present."""
    path = session_scan_path(database_path)
    if not path.is_file():
        return False
    try:
        path.unlink()
        logger.info("Deleted session library scan at %s", path)
        return True
    except OSError as exc:
        logger.warning("Could not delete session library scan at %s: %s", path, exc)
        return False


def list_session_scan_paths() -> List[Path]:
    """Return every persisted session scan pickle under ``output/library_data/.session``."""
    session_root = get_library_data_dir() / ".session"
    if not session_root.is_dir():
        return []
    return sorted(path for path in session_root.glob("*/scan.pkl") if path.is_file())


def other_session_scan_paths(database_path: Path) -> List[Path]:
    """Session scan pickles for every database except ``database_path``."""
    keep = session_scan_path(database_path).resolve()
    return [path for path in list_session_scan_paths() if path.resolve() != keep]


def delete_other_session_scans(database_path: Path) -> List[Path]:
    """
    Remove session scan pickles for every database except ``database_path``.

    Returns:
        Paths that were successfully deleted.
    """
    deleted: List[Path] = []
    for path in other_session_scan_paths(database_path):
        try:
            path.unlink()
            deleted.append(path)
            logger.info("Deleted previous session library scan at %s", path)
        except OSError as exc:
            logger.warning("Could not delete session library scan at %s: %s", path, exc)
    return deleted


def any_session_scan_exists() -> bool:
    """True when at least one session scan pickle exists on disk."""
    return bool(list_session_scan_paths())


def delete_all_session_scans() -> int:
    """
    Remove every persisted session scan pickle.

    Returns:
        Number of scan files successfully deleted.
    """
    deleted = 0
    for path in list_session_scan_paths():
        try:
            path.unlink()
            deleted += 1
            logger.info("Deleted session library scan at %s", path)
        except OSError as exc:
            logger.warning("Could not delete session library scan at %s: %s", path, exc)
    return deleted


def session_scan_exists(database_path: Path) -> bool:
    """True when a session scan pickle exists on disk for this database."""
    return session_scan_path(database_path).is_file()


def _sanitize_filename_token(value: str, *, max_len: int = 48) -> str:
    import re

    token = re.sub(r"[^\w\-]+", "_", str(value).strip())
    token = token.strip("_")
    if not token:
        return "unknown"
    return token[:max_len]


def suggested_scan_export_filename(
    database_path: Path,
    scan: "LibraryScanData",
) -> str:
    """Build a descriptive filename for an exported library scan pickle."""
    stem = sanitize_database_stem(database_path.stem)
    channel_tokens = [
        _sanitize_filename_token(name, max_len=24) for name in scan.channel_names[:3]
    ]
    channel_part = "-".join(channel_tokens) if channel_tokens else "no_channels"
    if len(scan.channel_names) > 3:
        channel_part += f"_plus{len(scan.channel_names) - 3}"
    n_entries = scan.entries_used or len(scan.entries)
    if scan.scanned_at is not None:
        ts = scan.scanned_at.astimezone(timezone.utc).strftime("%Y%m%d")
    else:
        ts = datetime.now(timezone.utc).strftime("%Y%m%d")
    return f"{stem}_library_scan_{channel_part}_{n_entries}entries_{ts}.pkl"


def export_scan_pickle(scan: "LibraryScanData", dest_path: Path) -> None:
    """Write a library scan to an external pickle path."""
    import pickle

    dest_path = Path(dest_path)
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    with dest_path.open("wb") as handle:
        pickle.dump(scan, handle, protocol=pickle.HIGHEST_PROTOCOL)
    logger.info("Exported library scan to %s", dest_path)


def load_scan_pickle(source_path: Path) -> "LibraryScanData":
    """Load a library scan pickle from any path."""
    import pickle

    from src.core.library_metrics import LibraryScanData

    source_path = Path(source_path)
    with source_path.open("rb") as handle:
        scan = pickle.load(handle)
    if not isinstance(scan, LibraryScanData):
        raise ValueError("File is not a valid LC-Seq library scan.")
    return scan


@dataclass
class ScanValidationReport:
    """Outcome of validating an imported scan against the active library."""

    ok: bool
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


def validate_scan_for_database(
    scan: "LibraryScanData",
    *,
    database_path: Path,
    config: "SpreadsheetConfig",
    compound_count: int,
) -> ScanValidationReport:
    """
    Check that a scan can be used with the active database and spreadsheet config.

    Channel names must match configured count columns. Entry counts and database
    provenance produce warnings when they look inconsistent.
    """
    errors: List[str] = []
    warnings: List[str] = []

    n_entries = len(scan.entries) or scan.entries_used
    if n_entries <= 0:
        errors.append("Scan contains no parsed entries.")

    if not scan.channel_names:
        errors.append("Scan has no count channels.")
    else:
        config_channels = set(config.count_names)
        unknown = [name for name in scan.channel_names if name not in config_channels]
        if unknown:
            errors.append(
                "Scan channels are not configured in the active spreadsheet: "
                f"{', '.join(unknown)}. "
                f"Configured count channels: {', '.join(config.count_names) or 'none'}."
            )

    if compound_count > 0 and n_entries > 0:
        ratio = n_entries / compound_count
        if ratio < 0.5:
            warnings.append(
                f"Scan has {n_entries:,} entries but the active database has "
                f"{compound_count:,} compounds ({ratio:.0%}). "
                "The scan may belong to a different library."
            )
        elif ratio > 1.05:
            warnings.append(
                f"Scan has {n_entries:,} entries, more than the {compound_count:,} "
                "compounds in the active database."
            )

    if scan.source_database_name and scan.source_database_name != database_path.name:
        warnings.append(
            f"Scan was saved from database “{scan.source_database_name}” but the active "
            f"database is “{database_path.name}”."
        )

    return ScanValidationReport(ok=not errors, errors=errors, warnings=warnings)


def load_session_scan(database_path: Path) -> Optional["LibraryScanData"]:
    """Load a previously saved session scan, if present."""
    import pickle

    from src.core.library_metrics import LibraryScanData

    path = session_scan_path(database_path)
    if not path.is_file():
        return None
    try:
        with path.open("rb") as handle:
            scan = pickle.load(handle)
        if not isinstance(scan, LibraryScanData):
            return None
        return scan
    except (OSError, pickle.PickleError, TypeError) as exc:
        logger.warning("Could not load session library scan from %s: %s", path, exc)
        return None


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
        "signal_quality_alpha": snapshot.signal_quality_alpha,
        "signal_quality_options": _signal_quality_options_to_dict(
            snapshot.signal_quality_options
        ),
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

    legacy_alpha = float(data.get("signal_quality_alpha", 0.001))
    signal_quality_options = _signal_quality_options_from_dict(
        data.get("signal_quality_options")
        if isinstance(data.get("signal_quality_options"), dict)
        else None,
        legacy_alpha=legacy_alpha,
    )

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
        signal_quality_options=signal_quality_options,
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


def delete_snapshot_artifacts(json_path: Path) -> bool:
    """
    Remove one saved snapshot JSON file and its companion ``*_plots`` directory.

    Returns:
        True when the JSON file was removed or was already absent.
    """
    path = Path(json_path)
    ok = True
    try:
        if path.is_file():
            path.unlink()
            logger.info("Removed library data snapshot: %s", path)
    except OSError as exc:
        logger.warning("Could not delete library data snapshot %s: %s", path, exc)
        ok = False
    plots_dir = snapshot_plots_dir(path)
    if plots_dir.is_dir():
        try:
            shutil.rmtree(plots_dir)
            logger.info("Removed snapshot plot directory: %s", plots_dir)
        except OSError as exc:
            logger.warning("Could not delete snapshot plot directory %s: %s", plots_dir, exc)
            ok = False
    return ok


def delete_all_saved_snapshots() -> int:
    """
    Delete every saved library metrics snapshot under ``output/library_data``.

    Returns:
        Number of snapshot JSON files successfully removed.
    """
    deleted = 0
    for path in list_snapshots(newest_first=False):
        if delete_snapshot_artifacts(path):
            deleted += 1
    return deleted


def database_paths_match(saved_path: str, active_path: Path) -> bool:
    """True when two database paths refer to the same file."""
    try:
        return Path(saved_path).resolve() == active_path.resolve()
    except OSError:
        return False
