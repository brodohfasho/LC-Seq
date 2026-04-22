# scripts/full_fraction_nonzero_coverage.py
"""
Command-line analysis: fraction of compounds with a strictly positive count
at every consensus time point (fraction).

Missing spreadsheet time points (e.g. omitted zeros in the export) are treated
as absent coverage for that fraction. Consensus times default to the sorted
union of all observed times across successfully parsed compounds; optionally
use a reference list (e.g. 94 canonical fraction times).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, Iterable, List, Sequence, Set, Tuple

import pandas as pd

# Project imports expect repository root on sys.path
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from src.core.data_processor import DataProcessor
from src.core.data_store import DataStore
from src.models.compound import Compound
from src.models.spreadsheet_config import SpreadsheetConfig


def _load_spreadsheet_config(path: Path) -> SpreadsheetConfig:
    """Load SpreadsheetConfig from JSON (named-config wrapper or flat dict)."""
    with path.open(encoding="utf-8-sig") as handle:
        data = json.load(handle)
    payload = data.get("config", data)
    return SpreadsheetConfig.from_dict(payload)


def _load_spreadsheet(path: Path) -> pd.DataFrame:
    """Load CSV or Excel into a DataFrame."""
    suffix = path.suffix.lower()
    if suffix == ".csv":
        return pd.read_csv(path, encoding="utf-8")
    if suffix in (".xlsx", ".xls"):
        engine = "openpyxl" if suffix == ".xlsx" else "xlrd"
        return pd.read_excel(path, engine=engine)
    raise ValueError(f"Unsupported spreadsheet type: {path}")


def _load_reference_times(path: Path) -> List[float]:
    """Load one fraction time per line; allow # comments and blank lines."""
    times: List[float] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        times.append(float(line))
    if not times:
        raise ValueError(f"No times parsed from reference file: {path}")
    return times


def _normalize_time(value: float, decimals: int) -> float:
    """Round time for stable set membership across compounds."""
    return round(float(value), decimals)


def _compound_time_count_map(
    compound: Compound,
    decimals: int,
    count_names: Sequence[str],
) -> Dict[float, Dict[str, float]]:
    """
    Map normalized time -> count name -> value (last wins if duplicates).
    """
    out: Dict[float, Dict[str, float]] = {}
    for dp in compound.data_points:
        key = _normalize_time(dp.time, decimals)
        bucket = out.setdefault(key, {})
        for name in count_names:
            val = dp.counts.get(name)
            if val is not None:
                bucket[name] = float(val)
    return out


def _compound_covers_consensus(
    compound: Compound,
    consensus: Sequence[float],
    decimals: int,
    count_names: Sequence[str],
) -> bool:
    """True if compound has count > 0 for every count_names at every consensus time."""
    by_time = _compound_time_count_map(compound, decimals, count_names)
    for t in consensus:
        key = _normalize_time(t, decimals)
        counts = by_time.get(key)
        if not counts:
            return False
        for name in count_names:
            val = counts.get(name)
            if val is None or val <= 0:
                return False
    return True


def _consensus_from_union(compounds: Iterable[Compound], decimals: int) -> List[float]:
    """Sorted union of normalized times across compounds."""
    seen: Set[float] = set()
    for compound in compounds:
        for dp in compound.data_points:
            seen.add(_normalize_time(dp.time, decimals))
    return sorted(seen)


def _parse_compounds_from_spreadsheet(
    df: pd.DataFrame,
    config: SpreadsheetConfig,
) -> Tuple[List[Compound], int, int]:
    """
    Returns (compounds, successful_rows, failed_rows).
    """
    processor = DataProcessor()
    compounds: List[Compound] = []
    failed = 0
    for row_number, (_, row) in enumerate(df.iterrows(), start=1):
        compound, result = processor.parse_dataframe_row_to_compound(
            row, config, row_number
        )
        if compound is not None:
            compounds.append(compound)
        else:
            failed += 1
    return compounds, len(compounds), failed


def _load_compounds_from_database(db_path: Path) -> List[Compound]:
    store = DataStore(db_path=db_path, use_memory=False)
    try:
        ids = store.get_all_compound_ids()
        out: List[Compound] = []
        for compound_id in ids:
            loaded = store.get_compound(compound_id)
            if loaded is not None:
                out.append(loaded)
        return out
    finally:
        store.close()


def _resolve_count_names(config: SpreadsheetConfig, args: argparse.Namespace) -> List[str]:
    if args.require_all_count_columns:
        return list(config.count_names)
    if args.count_name is not None:
        if args.count_name not in config.count_names:
            raise ValueError(
                f"--count-name {args.count_name!r} not in config count_names: "
                f"{config.count_names}"
            )
        return [args.count_name]
    if not config.count_names:
        raise ValueError("SpreadsheetConfig has no count_names.")
    return [config.count_names[0]]


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Report what fraction of compounds have strictly positive counts at "
            "every consensus time point."
        )
    )
    src = parser.add_mutually_exclusive_group(required=True)
    src.add_argument(
        "--spreadsheet",
        type=Path,
        help="Path to CSV or Excel file (same layout as LC-Seq processing).",
    )
    src.add_argument(
        "--database",
        type=Path,
        help="Path to an LC-Seq SQLite database produced by bulk processing.",
    )
    parser.add_argument(
        "--config",
        type=Path,
        required=True,
        help="JSON spreadsheet configuration (named config file or flat dict).",
    )
    parser.add_argument(
        "--reference-times",
        type=Path,
        default=None,
        help=(
            "Optional text file: one canonical fraction time per line. "
            "When set, consensus is exactly this list (after rounding), not the union."
        ),
    )
    parser.add_argument(
        "--expected-timepoints",
        type=int,
        default=None,
        help="If set, compare consensus size to this value and warn or fail (see --strict-expected).",
    )
    parser.add_argument(
        "--strict-expected",
        action="store_true",
        help="Exit with code 2 if consensus size != --expected-timepoints.",
    )
    parser.add_argument(
        "--time-rounding-decimals",
        type=int,
        default=6,
        help="Decimal places used when matching times across compounds (default: 6).",
    )
    parser.add_argument(
        "--count-name",
        type=str,
        default=None,
        help="Which count column to evaluate (default: first entry in config count_names).",
    )
    parser.add_argument(
        "--require-all-count-columns",
        action="store_true",
        help="Require every configured count column to be > 0 at each consensus time.",
    )
    return parser


def main() -> int:
    parser = _build_arg_parser()
    args = parser.parse_args()

    config = _load_spreadsheet_config(args.config)
    if not config.is_complete():
        print("Configuration JSON is incomplete (delimiters, time index, counts).", file=sys.stderr)
        return 1

    count_names = _resolve_count_names(config, args)
    decimals = args.time_rounding_decimals

    if args.spreadsheet is not None:
        df = _load_spreadsheet(args.spreadsheet)
        compounds, ok_rows, failed_rows = _parse_compounds_from_spreadsheet(df, config)
        source_label = str(args.spreadsheet)
    else:
        compounds = _load_compounds_from_database(args.database)
        ok_rows = len(compounds)
        failed_rows = 0
        source_label = str(args.database)

    if not compounds:
        print("No compounds loaded; nothing to analyze.", file=sys.stderr)
        return 1

    if args.reference_times is not None:
        raw_ref = _load_reference_times(args.reference_times)
        consensus = []
        seen_ref: Set[float] = set()
        for t in raw_ref:
            key = _normalize_time(t, decimals)
            if key not in seen_ref:
                seen_ref.add(key)
                consensus.append(key)
    else:
        consensus = _consensus_from_union(compounds, decimals)

    n_consensus = len(consensus)
    if args.expected_timepoints is not None and n_consensus != args.expected_timepoints:
        msg = (
            f"Consensus has {n_consensus} time points; "
            f"--expected-timepoints was {args.expected_timepoints}."
        )
        if args.strict_expected:
            print(msg, file=sys.stderr)
            return 2
        print(f"Warning: {msg}")

    qualifying = [
        c
        for c in compounds
        if _compound_covers_consensus(c, consensus, decimals, count_names)
    ]
    n_total = len(compounds)
    n_qual = len(qualifying)
    pct = (100.0 * n_qual / n_total) if n_total else 0.0

    print("Full-fraction strictly-positive coverage analysis")
    print(f"  Source: {source_label}")
    print(f"  Config: {args.config}")
    print(f"  Count column(s) evaluated: {count_names}")
    print(f"  Time rounding (decimals): {decimals}")
    print(f"  Consensus time points: {n_consensus}")
    if n_consensus:
        head = ", ".join(str(t) for t in consensus[:5])
        tail = ", ".join(str(t) for t in consensus[-5:])
        print(f"  First times: {head}")
        print(f"  Last times: {tail}")
    if args.spreadsheet is not None:
        print(f"  Rows parsed to compounds: {ok_rows}")
        print(f"  Rows skipped / failed parse: {failed_rows}")
    print(f"  Compounds analyzed: {n_total}")
    print(f"  Compounds with >0 at every consensus time: {n_qual}")
    print(f"  Percentage: {pct:.4f}%")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
