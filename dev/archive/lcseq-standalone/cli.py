# dev/archive/lcseq-standalone/cli.py
"""LC-Seq command-line interface (archived standalone tooling).

Wires `parse_xlsx → evaluate_library → render_pruned_tree` end-to-end.

Examples
--------
    # Full library, summary only (no figure produced — too dense to be useful).
    lcseq run data.xlsx --unit minutes --tolerance 0.5 --alpha 1e-3

    # Sub-library with a figure rendered.
    lcseq run data.xlsx --unit minutes --tolerance 0.5 \\
        --bbs Val Phe Leu --out val_phe_leu_tree
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

from lcseq import evaluate_library
from lcseq.render import render_pruned_tree

from lcseq_io import parse_xlsx


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="lcseq",
        description="Run the LC-Seq pedigree-pruning pipeline on an LDEL master xlsx.",
    )
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="parse → evaluate → render")
    r.add_argument("xlsx", type=Path, help="Path to the master xlsx file.")
    r.add_argument("--lid", default="DEL-0044",
                   help="Library/condition id to keep (default: DEL-0044, linear).")
    r.add_argument("--null-token", default="AgxNull",
                   help="Token marking unfilled positions (default: AgxNull).")
    r.add_argument("--channel", choices=("raw", "scaled"), default="scaled",
                   help="Signal channel: raw=sig1, scaled=sig2 (default: scaled).")
    r.add_argument("--source-unit", choices=("seconds", "minutes"), default="seconds",
                   help="Time unit of rt values in the file (default: seconds).")
    r.add_argument("--unit", choices=("seconds", "minutes"), default="seconds",
                   help="Operating/output unit; tolerance is in this unit (default: seconds).")
    r.add_argument("--tolerance", type=float, default=30.0,
                   help="± window for replicate pick agreement (in --unit; default: 30).")
    r.add_argument("--alpha", type=float, default=1e-3,
                   help="Per-peak FDR threshold for the NB significance test "
                        "(default: 1e-3).")
    r.add_argument("--bbs", nargs="+", default=None,
                   help="Restrict to a sub-library of these building blocks. "
                        "Default: use all BBs found in the data.")
    r.add_argument("--out", type=Path, default=None,
                   help="Output path stem; renderer appends format ext. "
                        "Omit to skip rendering (useful for full-library runs where the "
                        "figure would be unreadably dense).")
    r.add_argument("--format", default="png",
                   help="Image format passed to graphviz (default: png).")
    r.add_argument("--layout", default="twopi",
                   help="Graphviz layout engine (default: twopi).")
    r.add_argument("--no-failed", action="store_true",
                   help="Hide failed trim points; render passed nodes only.")
    r.add_argument("--no-rt-labels", action="store_true",
                   help="Omit the chosen rt from passing-node labels.")
    r.add_argument("--keep-dot", action="store_true",
                   help="Keep the intermediate .dot source file.")
    return p


def _restrict_to_bbs(
    bbs_per_position: list[list[str]],
    chromatograms: dict,
    chosen: list[str],
    null_token: str,
) -> tuple[list[list[str]], dict]:
    """Filter chromatograms and per-position BB sets to a chosen subset.

    `chosen` is intersected with each position's allowed BBs (so a BB that the user
    requests but doesn't appear at any position is silently dropped). Chromatograms whose
    positions contain a non-null BB outside the chosen set are removed.
    """
    chosen_set = set(chosen)
    bbs_per_position_filtered = [
        sorted(set(bbs) & chosen_set) for bbs in bbs_per_position
    ]
    allowed = chosen_set | {null_token}
    kept = {
        positions: chrom
        for positions, chrom in chromatograms.items()
        if all(p in allowed for p in positions)
    }
    return bbs_per_position_filtered, kept


def _summarise(records) -> None:
    by_tier_pass: Counter[int] = Counter()
    by_tier_fail: Counter[int] = Counter()
    by_tier_pruned: Counter[int] = Counter()
    for r in records:
        if r.passed:
            by_tier_pass[r.tier] += 1
        elif r.evaluated:
            by_tier_fail[r.tier] += 1
        else:
            by_tier_pruned[r.tier] += 1
    tiers = sorted(set(by_tier_pass) | set(by_tier_fail) | set(by_tier_pruned))
    total_pass = sum(by_tier_pass.values())
    total_fail = sum(by_tier_fail.values())
    total_pruned = sum(by_tier_pruned.values())
    print(f"  total: {len(records)}  passed={total_pass}, failed={total_fail}, pruned={total_pruned}")
    for t in tiers:
        print(f"    tier {t}: pass={by_tier_pass[t]:>6}  fail={by_tier_fail[t]:>4}  pruned={by_tier_pruned[t]:>6}")


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.cmd != "run":
        return 0

    print(f"Parsing {args.xlsx} (lid={args.lid}, channel={args.channel}, unit={args.unit})...")
    bbs_per_position, chroms = parse_xlsx(
        args.xlsx,
        lid=args.lid,
        null_token=args.null_token,
        channel=args.channel,
        source_unit=args.source_unit,
        unit=args.unit,
    )
    n = len(bbs_per_position)
    print(f"  N={n}, BBs per position={[len(b) for b in bbs_per_position]}, "
          f"{len(chroms)} chromatograms")

    if args.bbs:
        bbs_per_position, chroms = _restrict_to_bbs(
            bbs_per_position, chroms, args.bbs, args.null_token
        )
        print(f"  --bbs filter → BBs per position={[len(b) for b in bbs_per_position]}, "
              f"{len(chroms)} chromatograms")

    print(f"Evaluating (tolerance={args.tolerance} {args.unit}, "
          f"alpha={args.alpha})...")
    records = evaluate_library(
        bbs_per_position=bbs_per_position,
        null_token=args.null_token,
        chromatograms=chroms,
        tolerance=args.tolerance,
        alpha=args.alpha,
    )
    _summarise(records)

    if args.out is None:
        print("(no --out → skipping render)")
    else:
        print(f"Rendering ({args.layout}, {args.format})...")
        out = render_pruned_tree(
            records,
            args.out,
            fmt=args.format,
            layout=args.layout,
            include_failed=not args.no_failed,
            show_rt=not args.no_rt_labels,
            keep_dot=args.keep_dot,
        )
        print(f"  wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
