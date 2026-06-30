"""I/O for the LDEL master xlsx.

Parses the spreadsheet into the input shape expected by `evaluate_library`:
a per-position list of allowed BBs and a dict of chromatograms keyed by positional
truncate tuples (one entry per position, in N→C order). The xlsx columns are stored
in synthetic order (BB1 = first added = C-terminus); the parser reverses to canonicalize
on N→C, which is the convention used throughout the rest of the system.

Time-unit handling is done here at the I/O boundary; the Rust kernel is unit-agnostic
(rt and tolerance must share the same unit, but the kernel doesn't know which).
"""
from __future__ import annotations

from pathlib import Path
from typing import Literal

import numpy as np
import openpyxl

Channel = Literal["raw", "scaled"]
TimeUnit = Literal["seconds", "minutes"]


def _unit_factor(source_unit: TimeUnit, unit: TimeUnit) -> float:
    if source_unit == unit:
        return 1.0
    if source_unit == "seconds" and unit == "minutes":
        return 1.0 / 60.0
    if source_unit == "minutes" and unit == "seconds":
        return 60.0
    raise ValueError(f"unsupported unit conversion: {source_unit} -> {unit}")


def _parse_datapoints(
    s: str | None,
    channel: Channel,
    factor: float,
) -> tuple[np.ndarray, np.ndarray]:
    """Decode 'time:sig1;sig2, time:sig1;sig2, ...' into (rt, intensity), sorted by rt.

    `channel="raw"` selects sig1; `channel="scaled"` selects sig2.
    `factor` multiplies rt for unit conversion.
    """
    if not s:
        return np.empty(0, dtype=np.float64), np.empty(0, dtype=np.float64)

    sig_idx = 0 if channel == "raw" else 1
    pairs: list[tuple[float, float]] = []
    for part in str(s).split(","):
        part = part.strip()
        if ":" not in part:
            continue
        time_str, signals = part.split(":", 1)
        sigs = [t.strip() for t in signals.split(";")]
        if len(sigs) <= sig_idx:
            continue
        try:
            t = float(time_str)
            v = float(sigs[sig_idx])
        except ValueError:
            continue
        pairs.append((t * factor, v))

    pairs.sort()
    if not pairs:
        return np.empty(0, dtype=np.float64), np.empty(0, dtype=np.float64)
    rt = np.fromiter((p[0] for p in pairs), dtype=np.float64, count=len(pairs))
    intensity = np.fromiter((p[1] for p in pairs), dtype=np.float64, count=len(pairs))
    return rt, intensity


def parse_xlsx(
    path: str | Path,
    *,
    lid: str = "DEL-0044",
    null_token: str = "AgxNull",
    channel: Channel = "scaled",
    source_unit: TimeUnit = "seconds",
    unit: TimeUnit = "seconds",
) -> tuple[list[list[str]], dict[tuple[str, ...], tuple[np.ndarray, np.ndarray]]]:
    """Parse the LDEL master xlsx.

    Parameters
    ----------
    path :
        Path to the xlsx file.
    lid :
        Library/condition id to keep (rows are filtered by the `lid` column).
        Default `"DEL-0044"` (linear).
    null_token :
        Token marking unfilled positions (matched against the BB Name columns).
    channel :
        Which signal to extract from `time:sig1;sig2`. `"raw"` = sig1, `"scaled"` = sig2.
    source_unit :
        Time unit of rt values in the file. `"seconds"` for the LDEL master xlsx.
    unit :
        Operating/output unit. rt arrays are converted to this unit; downstream `tolerance`
        and `alpha` must use the same unit.

    Returns
    -------
    (bbs_per_position, chromatograms)
        bbs_per_position : list of length N (number of `BB{i} Name` columns), each entry
            is the sorted list of distinct non-null BB names actually observed at that
            position in the kept rows. This drives the pedigree builder so it only
            enumerates physically realizable positional truncates.
        chromatograms : `dict[(bb1, bb2, ...), (rt, intensity)]`. The key is a tuple of the
            per-position BB names in N→C order, derived from the BB1/BB2/BB3 columns
            (xlsx columns are in synthetic / C→N order; the parser reverses). Tuple
            keys (not Common_Name strings) avoid collisions when BB names themselves
            contain `-` (e.g. cassette BBs like `"DLeu-DLeu-Pro"`).
    """
    path = Path(path)
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    ws = wb.worksheets[0]
    rows = ws.iter_rows(values_only=True)
    header = list(next(rows))

    i_lid = header.index("lid")
    i_dp = header.index("all_datapoints")
    bb_indices = [
        header.index(f"BB{i} Name") for i in (1, 2, 3) if f"BB{i} Name" in header
    ]
    n_positions = len(bb_indices)

    factor = _unit_factor(source_unit, unit)
    chromatograms: dict[tuple[str, ...], tuple[np.ndarray, np.ndarray]] = {}
    bbs_at: list[set[str]] = [set() for _ in range(n_positions)]

    # Reverse column order → N→C order. The xlsx has BB1, BB2, ... in synthetic
    # (column) order, where BB1 is added first and ends up at the C-terminus and the
    # last-added BB is at the N-terminus. We canonicalize on N→C reading throughout
    # the rest of the system, so reverse here at the boundary.
    bb_indices_n_to_c = list(reversed(bb_indices))

    for r in rows:
        if r[i_lid] != lid:
            continue
        positions = tuple(r[bi] for bi in bb_indices_n_to_c)
        if any(p is None for p in positions):
            continue
        chromatograms[positions] = _parse_datapoints(r[i_dp], channel, factor)
        for pos, p in enumerate(positions):
            if p != null_token:
                bbs_at[pos].add(p)

    bbs_per_position = [sorted(s) for s in bbs_at]
    return bbs_per_position, chromatograms
