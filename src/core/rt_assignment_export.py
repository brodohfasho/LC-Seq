# src/core/rt_assignment_export.py
"""Export assigned RTs and null-analysis results to spreadsheet."""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

import pandas as pd

from src.core.csv_io import CSV_EXPORT_ENCODING
from src.core.del_cycle_tree.bb_index_scheme import (
    build_bb_name_canonical_map,
    canonicalize_positions,
    normalize_bb_name,
)
from src.core.del_cycle_tree.models import CompoundRtAssignment, DelCycleTreeData
from src.core.del_cycle_tree.positions import positions_c_to_n
from src.core.data_store import DataStore
from src.models.compound import Compound
from src.models.compound_identity import build_compound_storage_id
from src.models.spreadsheet_config import SpreadsheetConfig


EXPORT_RT_SOURCE_COLUMN = "rt_source"
EXPORT_NULL_RT_VERIFIED_COLUMN = "null_rt_verified"
EXPORT_RT_THRESHOLD_COLUMN = "null_rt_threshold"

ExportProgressCallback = Optional[Callable[[int, int, str], None]]


@dataclass(frozen=True)
class RtSpreadsheetExportResult:
    """Summary of a spreadsheet RT export."""

    output_path: Path
    rows_written: int
    rows_assigned: int
    rows_with_verification: int = 0


def assigned_rt_column_name(time_unit: str) -> str:
    """Standard assigned RT column header for the active analysis time unit."""
    unit_suffix = "min" if str(time_unit).lower().startswith("min") else "s"
    return f"assigned_rt ({unit_suffix})"


def product_rt_column_name(time_unit: str) -> str:
    """Standard product RT column header for ``split_tree_products.csv``."""
    unit_suffix = "min" if str(time_unit).lower().startswith("min") else "s"
    return f"rt ({unit_suffix})"


def parse_null_rt_verified_metadata(value: object) -> Optional[bool]:
    """Parse TRUE/FALSE pass-fail cells exported by LC-Seq (or common synonyms)."""
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and not pd.isna(value):
        if value == 1:
            return True
        if value == 0:
            return False
    text = str(value).strip()
    if not text or text.lower() in {"na", "n/a", "nan", "-", ""}:
        return None
    lowered = text.lower()
    if lowered in {"true", "t", "yes", "y", "1", "pass", "passed"}:
        return True
    if lowered in {"false", "f", "no", "n", "0", "fail", "failed"}:
        return False
    return None


def format_null_rt_verified(value: Optional[bool]) -> str:
    """Spreadsheet-friendly pass/fail token."""
    if value is None:
        return ""
    return "TRUE" if value else "FALSE"


def spreadsheet_export_columns(config: SpreadsheetConfig) -> List[str]:
    """Input spreadsheet columns to include when exporting from the database."""
    columns: List[str] = []
    for name in (
        config.compound_id_column,
        config.compound_variant_column,
        config.chromatographic_data_column,
        *config.active_bb_position_columns(),
        *config.selected_metadata_columns,
    ):
        if not name or not str(name).strip():
            continue
        column = str(name).strip()
        if column not in columns:
            columns.append(column)
    return columns


def build_verification_overrides_from_metadata(
    compounds: Sequence[Compound],
    config: SpreadsheetConfig,
    *,
    column: str,
) -> Dict[Tuple[str, ...], bool]:
    """
    Read precomputed null pass/fail values from compound metadata.

    Used when regenerating a split-tree from an exported RT analysis spreadsheet.
    """
    from src.core.del_cycle_tree.models import DelCycleRow

    null_token = normalize_bb_name(config.null_token)
    n_cycles = config.library_cycle_count
    del_rows = [
        DelCycleRow(positions=positions, rt=0.0)
        for compound in compounds
        if (positions := positions_c_to_n(compound, config)) is not None
    ]
    canonical_by_lower = build_bb_name_canonical_map(del_rows, null_token)
    overrides: Dict[Tuple[str, ...], bool] = {}
    for compound in compounds:
        positions = positions_c_to_n(compound, config)
        if positions is None or len(positions) != n_cycles:
            continue
        if any(normalize_bb_name(bb) == null_token for bb in positions):
            continue
        parsed = parse_null_rt_verified_metadata(compound.metadata.get(column))
        if parsed is None:
            continue
        key = canonicalize_positions(
            tuple(normalize_bb_name(bb) for bb in positions),
            null_token=null_token,
            canonical_by_lower=canonical_by_lower,
        )
        overrides[key] = parsed
    return overrides


def build_null_verification_by_compound_id(
    compounds: Sequence[Compound],
    config: SpreadsheetConfig,
    del_data: DelCycleTreeData,
) -> Dict[str, Optional[bool]]:
    """Map storage compound id → null-analysis pass/fail for full products."""
    from src.core.del_cycle_tree.models import DelCycleRow

    null_token = normalize_bb_name(config.null_token)
    n_cycles = config.library_cycle_count
    del_rows = [
        DelCycleRow(positions=positions, rt=0.0)
        for compound in compounds
        if (positions := positions_c_to_n(compound, config)) is not None
    ]
    canonical_by_lower = build_bb_name_canonical_map(del_rows, null_token)
    lookup: Dict[str, Optional[bool]] = {}
    for compound in compounds:
        positions = positions_c_to_n(compound, config)
        if positions is None or len(positions) != n_cycles:
            lookup[compound.compound_id] = None
            continue
        if any(normalize_bb_name(bb) == null_token for bb in positions):
            lookup[compound.compound_id] = None
            continue
        canonical = canonicalize_positions(
            tuple(normalize_bb_name(bb) for bb in positions),
            null_token=null_token,
            canonical_by_lower=canonical_by_lower,
        )
        info = del_data.verified_sequences.get(canonical)
        if info is None and canonical != positions:
            info = del_data.verified_sequences.get(positions)
        lookup[compound.compound_id] = bool(info.success) if info is not None else None
    return lookup


def enrich_assignments_with_null_verification(
    assignments: Sequence[CompoundRtAssignment],
    compounds: Sequence[Compound],
    config: SpreadsheetConfig,
    del_data: Optional[DelCycleTreeData],
) -> List[CompoundRtAssignment]:
    """Attach null-analysis pass/fail to each assignment when tree data is available."""
    if del_data is None:
        return list(assignments)
    verification = build_null_verification_by_compound_id(compounds, config, del_data)
    enriched: List[CompoundRtAssignment] = []
    for item in assignments:
        verified = verification.get(item.compound_id)
        if verified is None and item.null_rt_verified is None:
            enriched.append(item)
            continue
        enriched.append(
            replace(
                item,
                null_rt_verified=verified if verified is not None else item.null_rt_verified,
            )
        )
    return enriched


def _read_spreadsheet(path: Path, sheet_name: Optional[str]) -> pd.DataFrame:
    suffix = path.suffix.lower()
    if suffix == ".csv":
        return pd.read_csv(path)
    if suffix in (".xlsx", ".xls"):
        return pd.read_excel(
            path,
            sheet_name=sheet_name or 0,
            engine="openpyxl" if suffix == ".xlsx" else "xlrd",
        )
    raise ValueError(f"Unsupported spreadsheet format: {path.suffix}")


def _write_spreadsheet(
    df: pd.DataFrame,
    output_path: Path,
    *,
    sheet_name: Optional[str],
) -> None:
    suffix = output_path.suffix.lower()
    if suffix == ".csv":
        df.to_csv(output_path, index=False, encoding=CSV_EXPORT_ENCODING)
        return
    if suffix in (".xlsx", ".xls"):
        with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
            target_sheet = sheet_name or "Sheet1"
            df.to_excel(writer, sheet_name=target_sheet, index=False)
        return
    df.to_csv(output_path, index=False, encoding=CSV_EXPORT_ENCODING)


def _assignment_lookup(
    assignments: Sequence[CompoundRtAssignment],
) -> Dict[str, CompoundRtAssignment]:
    return {item.compound_id: item for item in assignments}


def _row_storage_id(row: pd.Series, config: SpreadsheetConfig) -> Optional[str]:
    id_col = config.compound_id_column
    if id_col not in row.index:
        return None
    primary = row[id_col]
    if pd.isna(primary) or not str(primary).strip():
        return None
    variant: Optional[str] = None
    variant_col = config.compound_variant_column
    if variant_col and variant_col in row.index:
        raw_variant = row[variant_col]
        if raw_variant is not None and not pd.isna(raw_variant) and str(raw_variant).strip():
            variant = str(raw_variant).strip()
    return build_compound_storage_id(str(primary).strip(), variant)


def _spreadsheet_row_from_compound(
    compound: Compound,
    config: SpreadsheetConfig,
    *,
    raw_chromatographic_data: Optional[str] = None,
) -> Dict[str, object]:
    """Rebuild one input-style spreadsheet row from database metadata."""
    row: Dict[str, object] = {}
    primary = compound.primary_compound_id or compound.compound_id
    primary_from_meta = compound.metadata.get(config.compound_id_column)
    if primary_from_meta is not None and str(primary_from_meta).strip():
        primary = str(primary_from_meta).strip()
    row[config.compound_id_column] = primary

    if config.compound_variant_column:
        variant = compound.variant_label
        if variant is None:
            variant = compound.metadata.get(config.compound_variant_column)
        row[config.compound_variant_column] = (
            "" if variant is None or (isinstance(variant, float) and pd.isna(variant)) else variant
        )

    chrom = raw_chromatographic_data
    if chrom is None:
        chrom = compound.metadata.get(config.chromatographic_data_column, "")
    row[config.chromatographic_data_column] = chrom or ""

    for column in spreadsheet_export_columns(config):
        if column in row:
            continue
        value = compound.metadata.get(column, "")
        if value is None or (isinstance(value, float) and pd.isna(value)):
            value = ""
        row[column] = value
    row["_storage_id"] = compound.compound_id
    return row


def build_spreadsheet_rows_from_compounds(
    compounds: Sequence[Compound],
    config: SpreadsheetConfig,
    store: DataStore,
    *,
    progress_callback: ExportProgressCallback = None,
) -> List[Dict[str, object]]:
    """Build export rows from already-loaded compounds (one batched raw-chrom fetch)."""
    compound_ids = [compound.compound_id for compound in compounds]
    raw_by_id = store.load_raw_chromatogram_map(compound_ids)
    rows: List[Dict[str, object]] = []
    total = len(compounds)
    for index, compound in enumerate(compounds, start=1):
        rows.append(
            _spreadsheet_row_from_compound(
                compound,
                config,
                raw_chromatographic_data=raw_by_id.get(compound.compound_id),
            )
        )
        if progress_callback is not None and (index % 5000 == 0 or index == total):
            progress_callback(
                index,
                total,
                f"Preparing export rows… {index:,} / {total:,}",
            )
    return rows


def load_spreadsheet_rows_from_store(
    store: DataStore,
    config: SpreadsheetConfig,
    *,
    metadata_columns: Optional[Sequence[str]] = None,
    progress_callback: ExportProgressCallback = None,
) -> List[Dict[str, object]]:
    """
    Reconstruct input-style spreadsheet rows from the active library database.

    Chromatogram text comes from ``raw_chromatographic_data`` when present (index DBs).
    """
    compounds = load_compounds_for_export(
        store,
        config,
        progress_callback=progress_callback,
    )
    return build_spreadsheet_rows_from_compounds(
        compounds,
        config,
        store,
        progress_callback=progress_callback,
    )


def load_compounds_for_export(
    store: DataStore,
    config: SpreadsheetConfig,
    *,
    progress_callback: ExportProgressCallback = None,
) -> List[Compound]:
    """Load compound metadata for every library row (no chromatogram parsing)."""
    from src.core.lineage_service import load_all_compound_metadata

    return load_all_compound_metadata(
        store,
        metadata_columns=config.selected_metadata_columns,
        progress_callback=progress_callback,
    )


def _append_export_columns(
    df: pd.DataFrame,
    config: SpreadsheetConfig,
    assignments: Sequence[CompoundRtAssignment],
    *,
    time_unit: str,
    rt_threshold: Optional[float],
    storage_id_series: Optional[pd.Series] = None,
) -> Tuple[pd.DataFrame, int, int]:
    """Add LC-Seq RT analysis columns; return (df, assigned_count, verified_count)."""
    lookup = _assignment_lookup(assignments)
    rt_column = assigned_rt_column_name(time_unit)
    assigned_values: List[object] = []
    source_values: List[object] = []
    verified_values: List[object] = []
    threshold_values: List[object] = []
    assigned_count = 0
    verified_count = 0
    threshold_text = "" if rt_threshold is None else float(rt_threshold)

    if storage_id_series is None:
        storage_ids = [
            _row_storage_id(row, config) for _, row in df.iterrows()
        ]
    else:
        storage_ids = storage_id_series.tolist()

    for storage_id in storage_ids:
        entry = lookup.get(storage_id) if storage_id is not None else None
        if entry is None:
            assigned_values.append("")
            source_values.append("")
            verified_values.append("")
            threshold_values.append(threshold_text)
            continue
        assigned_values.append(entry.assigned_rt)
        source_values.append(entry.rt_source)
        verified_values.append(format_null_rt_verified(entry.null_rt_verified))
        threshold_values.append(threshold_text)
        assigned_count += 1
        if entry.null_rt_verified is not None:
            verified_count += 1

    df[rt_column] = assigned_values
    df[EXPORT_RT_SOURCE_COLUMN] = source_values
    df[EXPORT_NULL_RT_VERIFIED_COLUMN] = verified_values
    df[EXPORT_RT_THRESHOLD_COLUMN] = threshold_values
    return df, assigned_count, verified_count


def export_assigned_rts_spreadsheet(
    source_path: str | Path,
    output_path: str | Path,
    config: SpreadsheetConfig,
    assignments: Sequence[CompoundRtAssignment],
    *,
    sheet_name: Optional[str] = None,
    time_unit: str = "seconds",
    rt_threshold: Optional[float] = None,
) -> RtSpreadsheetExportResult:
    """
    Copy the input spreadsheet and append LC-Seq RT analysis columns.

    Adds assigned RT, RT source, null pass/fail, and the verification threshold.
    """
    src = Path(source_path)
    out = Path(output_path)
    df = _read_spreadsheet(src, sheet_name)
    df, assigned_count, verified_count = _append_export_columns(
        df,
        config,
        assignments,
        time_unit=time_unit,
        rt_threshold=rt_threshold,
    )
    _write_spreadsheet(df, out, sheet_name=sheet_name)
    return RtSpreadsheetExportResult(
        output_path=out,
        rows_written=len(df),
        rows_assigned=assigned_count,
        rows_with_verification=verified_count,
    )


def export_rt_analysis_from_database(
    output_path: str | Path,
    config: SpreadsheetConfig,
    spreadsheet_rows: Sequence[Dict[str, object]],
    assignments: Sequence[CompoundRtAssignment],
    *,
    sheet_name: Optional[str] = None,
    time_unit: str = "seconds",
    rt_threshold: Optional[float] = None,
) -> RtSpreadsheetExportResult:
    """
    Write a new spreadsheet from database rows plus LC-Seq RT analysis columns.

    Does not require the original input spreadsheet file on disk.
    """
    out = Path(output_path)
    export_columns = spreadsheet_export_columns(config)
    records: List[Dict[str, object]] = []
    storage_ids: List[Optional[str]] = []
    for row in spreadsheet_rows:
        storage_id = str(row.get("_storage_id", "")).strip() or None
        storage_ids.append(storage_id)
        record = {column: row.get(column, "") for column in export_columns}
        records.append(record)
    df = pd.DataFrame(records, columns=export_columns)
    storage_series = pd.Series(storage_ids, dtype=object)
    df, assigned_count, verified_count = _append_export_columns(
        df,
        config,
        assignments,
        time_unit=time_unit,
        rt_threshold=rt_threshold,
        storage_id_series=storage_series,
    )
    _write_spreadsheet(df, out, sheet_name=sheet_name)
    return RtSpreadsheetExportResult(
        output_path=out,
        rows_written=len(df),
        rows_assigned=assigned_count,
        rows_with_verification=verified_count,
    )


def export_rt_analysis_spreadsheet(
    output_path: str | Path,
    config: SpreadsheetConfig,
    assignments: Sequence[CompoundRtAssignment],
    *,
    source_path: Optional[str | Path] = None,
    sheet_name: Optional[str] = None,
    time_unit: str = "seconds",
    rt_threshold: Optional[float] = None,
    spreadsheet_rows: Optional[Sequence[Dict[str, object]]] = None,
) -> RtSpreadsheetExportResult:
    """
    Export RT analysis to spreadsheet, merging into ``source_path`` when available.

    When ``source_path`` is missing, writes a new file from ``spreadsheet_rows``
    (typically reconstructed from the library database).
    """
    if source_path is not None and Path(source_path).is_file():
        return export_assigned_rts_spreadsheet(
            source_path,
            output_path,
            config,
            assignments,
            sheet_name=sheet_name,
            time_unit=time_unit,
            rt_threshold=rt_threshold,
        )
    if spreadsheet_rows is None:
        raise ValueError(
            "No source spreadsheet is available and no database rows were provided."
        )
    return export_rt_analysis_from_database(
        output_path,
        config,
        spreadsheet_rows,
        assignments,
        sheet_name=sheet_name,
        time_unit=time_unit,
        rt_threshold=rt_threshold,
    )
