"""Tests for `lcseq.render.render_pruned_tree`.

Uses a duck-typed mock record (a dataclass) for unit tests so we don't depend on the
PyO3 NodeRecord constructor; one integration test exercises the real eval → render path
against the real-data fixture.
"""
from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pytest

import lcseq
from lcseq.render import render_pruned_tree

FIXTURE = Path(__file__).resolve().parent.parent.parent / "tests" / "fixtures" / "real_sample.json"


@dataclass
class MockRecord:
    id: str
    label: str
    tier: int
    kind: str
    passed: bool
    evaluated: bool
    insufficient_data: bool = False
    # Algorithm's chosen rt is surfaced via three fields under the new naming:
    # bayesian_pick (multi-rep), score_test_rt (multi-rep prior), and
    # initial_most_significant_picks[0] (root / n=1 path).
    bayesian_pick: float | None = None
    score_test_rt: float | None = None
    initial_most_significant_picks: list[float | None] = field(default_factory=list)
    parent_ids: list[str] = field(default_factory=list)


def _has_dot() -> bool:
    return shutil.which("dot") is not None


# A tiny synthetic pruned tree:
#   ROOT (passed) → A (passed) → AA (passed)
#                 → B (failed)
# Root and AA are n=1 (compound), so chosen rt lives in initial_most_significant_picks[0].
# A is a multi-rep class (kind=class), so chosen rt is bayesian_pick.
TINY = [
    MockRecord("root", "ROOT", 0, "class", True, True,
               initial_most_significant_picks=[5.0]),
    MockRecord("a", "A", 1, "class", True, True,
               bayesian_pick=10.0, score_test_rt=10.0,
               parent_ids=["root"]),
    MockRecord("b", "B", 1, "class", False, True, parent_ids=["root"]),
    MockRecord("aa", "AA", 2, "compound", True, True,
               initial_most_significant_picks=[15.0],
               parent_ids=["a"]),
]


@pytest.mark.skipif(not _has_dot(), reason="graphviz `dot` binary not available")
def test_renders_pruned_tree_default(tmp_path: Path):
    out = render_pruned_tree(TINY, tmp_path / "tree")
    assert out.exists()
    assert out.suffix == ".png"
    assert out.stat().st_size > 0


@pytest.mark.skipif(not _has_dot(), reason="graphviz `dot` binary not available")
def test_default_includes_failed_trim_points(tmp_path: Path):
    out = render_pruned_tree(TINY, tmp_path / "tree", keep_dot=True)
    dot_path = out.with_suffix("")
    assert dot_path.exists()
    src = dot_path.read_text()
    # Default include_failed=True: failed trim point b IS shown.
    assert "\ta [" in src
    assert "\taa [" in src
    assert "\tb [" in src


@pytest.mark.skipif(not _has_dot(), reason="graphviz `dot` binary not available")
def test_include_failed_false_excludes_trim_points(tmp_path: Path):
    out = render_pruned_tree(TINY, tmp_path / "tree", include_failed=False, keep_dot=True)
    src = out.with_suffix("").read_text()
    assert "\tb [" not in src


@pytest.mark.skipif(not _has_dot(), reason="graphviz `dot` binary not available")
def test_root_is_grey(tmp_path: Path):
    out = render_pruned_tree(TINY, tmp_path / "tree", keep_dot=True)
    src = out.with_suffix("").read_text()
    root_line = next(ln for ln in src.splitlines() if ln.lstrip().startswith("root ["))
    assert "#d0d0d0" in root_line
    a_line = next(ln for ln in src.splitlines() if ln.lstrip().startswith("a ["))
    assert "#d0d0d0" not in a_line


@pytest.mark.skipif(not _has_dot(), reason="graphviz `dot` binary not available")
def test_failed_node_is_red(tmp_path: Path):
    out = render_pruned_tree(TINY, tmp_path / "tree", keep_dot=True)
    src = out.with_suffix("").read_text()
    b_line = next(ln for ln in src.splitlines() if ln.lstrip().startswith("b ["))
    assert "#e57373" in b_line


@pytest.mark.skipif(not _has_dot(), reason="graphviz `dot` binary not available")
def test_show_rt_includes_chosen_rt_in_label(tmp_path: Path):
    out = render_pruned_tree(TINY, tmp_path / "tree", show_rt=True, keep_dot=True)
    src = out.with_suffix("").read_text()
    assert "rt=10.0" in src


@pytest.mark.skipif(not _has_dot(), reason="graphviz `dot` binary not available")
def test_layout_engine_can_be_changed(tmp_path: Path):
    out = render_pruned_tree(TINY, tmp_path / "tree", layout="dot")
    assert out.exists() and out.stat().st_size > 0


@pytest.mark.skipif(not _has_dot() or not FIXTURE.exists(), reason="dot or fixture missing")
def test_real_eval_render_pipeline(tmp_path: Path):
    """End-to-end: real fixture → evaluate_library → render_pruned_tree."""
    fx = json.loads(FIXTURE.read_text())
    chroms = {
        tuple(name.split("-")): (
            np.asarray(c["rt"], dtype=np.float64),
            np.asarray(c["scaled"], dtype=np.float64),
        )
        for name, c in fx["chromatograms"].items()
    }
    records = lcseq.evaluate_library(
        bbs_per_position=[fx["building_blocks"]] * fx["n_positions"],
        null_token=fx["null_token"],
        chromatograms=chroms,
        tolerance=30.0,
        alpha=1e-3,
    )
    out = render_pruned_tree(records, tmp_path / "real_tree", keep_dot=True)
    assert out.exists() and out.stat().st_size > 0
    src = out.with_suffix("").read_text()
    # Spot-check: root + at least one tier-3 compound rendered. Which specific compound
    # passes is algorithm-dependent and may shift with future refinements.
    assert "ROOT" in src
    assert any(label in src for label in ("DNvl-DNvl-DNvl", "DPhe-DPhe-DPhe", "DNvl-DPhe-DNvl"))
