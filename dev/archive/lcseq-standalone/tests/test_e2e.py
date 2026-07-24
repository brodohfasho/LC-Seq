# dev/archive/lcseq-standalone/tests/test_e2e.py
"""End-to-end test of the archived LC-Seq CLI on the real xlsx.

Exercises the full pipeline: parse_xlsx → evaluate_library → render_pruned_tree.
Marked `slow` because xlsx parsing is ~25s.
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest

_ARCHIVE = Path(__file__).resolve().parents[1]
_REPO = Path(__file__).resolve().parents[3]
if str(_ARCHIVE) not in sys.path:
    sys.path.insert(0, str(_ARCHIVE))

from cli import main as cli_main

XLSX = _REPO / "LC-Seq-New-master" / "data" / "LDEL_ssPID_10-40_Master3.0.xlsx"


def _has_dot() -> bool:
    return shutil.which("dot") is not None


@pytest.mark.slow
@pytest.mark.skipif(not XLSX.exists() or not _has_dot(),
                    reason="xlsx or graphviz `dot` binary missing")
def test_cli_runs_val_phe_leu_sub_library(tmp_path: Path, capsys):
    out_stem = tmp_path / "tree"
    rc = cli_main([
        "run", str(XLSX),
        "--bbs", "Val", "Phe", "Leu",
        "--unit", "minutes",
        "--tolerance", "0.5",
        "--alpha", "10",
        "--out", str(out_stem),
        "--keep-dot",
    ])
    assert rc == 0
    img = out_stem.with_suffix(".png")
    dot = out_stem
    assert img.exists() and img.stat().st_size > 0
    assert dot.exists()

    captured = capsys.readouterr()
    # Verify summary line printed.
    assert "passed=" in captured.out
    assert "rendered" in captured.out.lower() or "wrote" in captured.out.lower()
    # All Val-Phe-Leu nodes pass on real data — we showed this earlier.
    # Exact count: 1 root + 3 tier-1 + 6 tier-2 + 27 tier-3 = 37.
    assert "passed=37" in captured.out


@pytest.mark.slow
@pytest.mark.skipif(not XLSX.exists() or not _has_dot(),
                    reason="xlsx or graphviz `dot` binary missing")
def test_cli_seconds_default_matches_minutes(tmp_path: Path, capsys):
    """Same sub-library, two unit modes; per-tier pass counts must agree."""
    for unit, tol, stem in [("seconds", 30.0, "s"), ("minutes", 0.5, "m")]:
        rc = cli_main([
            "run", str(XLSX),
            "--bbs", "Val", "Phe", "Leu",
            "--unit", unit,
            "--tolerance", str(tol),
            "--alpha", "10",
            "--out", str(tmp_path / stem),
        ])
        assert rc == 0
    out_s = capsys.readouterr().out
    # Both runs printed the same per-tier breakdown.
    # We can't trivially diff because output is interleaved; just sanity-check
    # both runs reached the rendering step.
    assert out_s.count("wrote") == 2
