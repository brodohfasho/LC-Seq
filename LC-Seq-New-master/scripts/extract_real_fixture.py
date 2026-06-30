"""One-off: pull a small slice of the real xlsx into a JSON fixture for Rust tests.

Picks the linear-library (DEL-0044) root, the first two BBs that have all three tier-1
positional replicates present, and the six positional truncates of the tier-2 class
formed by those two BBs.

Run:  uv run --with openpyxl python scripts/extract_real_fixture.py
"""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

import openpyxl

XLSX = Path(__file__).resolve().parent.parent / "data" / "LDEL_ssPID_10-40_Master3.0.xlsx"
OUT = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "real_sample.json"
NULL = "AgxNull"
LID = "DEL-0044"  # linear


def parse_datapoints(s: str | None) -> tuple[list[float], list[int], list[int]]:
    """Decode 'time:sig1;sig2, time:sig1;sig2, ...' → (rt, raw, scaled), sorted by rt."""
    if not s:
        return [], [], []
    rt: list[float] = []
    raw: list[int] = []
    scaled: list[int] = []
    for part in str(s).split(","):
        part = part.strip()
        if ":" not in part:
            continue
        time_str, signals = part.split(":", 1)
        sigs = [t.strip() for t in signals.split(";")]
        if len(sigs) < 2:
            continue
        try:
            rt.append(float(time_str))
            raw.append(int(float(sigs[0])))
            scaled.append(int(float(sigs[1])))
        except ValueError:
            continue
    indexed = sorted(zip(rt, raw, scaled))
    return [x[0] for x in indexed], [x[1] for x in indexed], [x[2] for x in indexed]


def is_tier_1(name: str) -> bool:
    return name.split("-").count(NULL) == 2


def tier_1_bb(name: str) -> str | None:
    return next((p for p in name.split("-") if p != NULL), None)


def main() -> None:
    wb = openpyxl.load_workbook(XLSX, read_only=True, data_only=True)
    ws = wb["Sheet1"]
    it = ws.iter_rows(values_only=True)
    header = list(next(it))
    i_name = header.index("Common_Name (N-->C)")
    i_lid = header.index("lid")
    i_dp = header.index("all_datapoints")

    linear: dict[str, tuple] = {}
    for r in it:
        if r[i_lid] == LID:
            linear[r[i_name]] = r

    tier1_by_bb: dict[str, list[str]] = defaultdict(list)
    for name in linear:
        if is_tier_1(name):
            bb = tier_1_bb(name)
            if bb:
                tier1_by_bb[bb].append(name)

    complete = [bb for bb, ns in tier1_by_bb.items() if len(ns) == 3]
    if len(complete) < 2:
        raise SystemExit(f"need ≥2 BBs with all 3 tier-1 reps; found {len(complete)}")
    chosen = sorted(complete)[:2]
    x, y = chosen

    selected: list[str] = [f"{NULL}-{NULL}-{NULL}"]
    for bb in chosen:
        selected.extend(sorted(tier1_by_bb[bb]))

    # All tier-2 classes over the chosen BBs: {x,x}, {y,y}, {x,y}.
    tier2_targets = [sorted([x, x]), sorted([y, y]), sorted([x, y])]
    for name in linear:
        parts = name.split("-")
        non_null = sorted(p for p in parts if p != NULL)
        if len(non_null) == 2 and non_null in tier2_targets:
            selected.append(name)

    # All tier-3 positional compounds over the chosen BBs (2^3 = 8).
    for name in linear:
        parts = name.split("-")
        if NULL not in parts and all(p in chosen for p in parts):
            selected.append(name)

    selected = list(dict.fromkeys(selected))  # dedupe, preserve order

    fixture: dict = {
        "lid": LID,
        "null_token": NULL,
        "n_positions": 3,
        "building_blocks": chosen,
        "chromatograms": {},
    }
    total_pts = 0
    for name in selected:
        if name not in linear:
            continue
        rt, raw, scaled = parse_datapoints(linear[name][i_dp])
        fixture["chromatograms"][name] = {"rt": rt, "raw": raw, "scaled": scaled}
        total_pts += len(rt)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(fixture, indent=2))
    print(f"BBs chosen: {chosen}")
    print(f"Truncates: {len(fixture['chromatograms'])} (root + {len(fixture['chromatograms']) - 1})")
    print(f"Total datapoints: {total_pts}")
    print(f"Wrote: {OUT}")


if __name__ == "__main__":
    main()
