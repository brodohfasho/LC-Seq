"""Smoke test the PyO3 bindings against the real-data fixture.

Compares Python-binding outcomes with the Rust integration test in tests/real_data.rs.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

import lcseq

FIXTURE = Path(__file__).resolve().parent.parent.parent / "tests" / "fixtures" / "real_sample.json"
TOLERANCE = 30.0
ALPHA = 1e-3


def _load_fixture() -> dict:
    return json.loads(FIXTURE.read_text())


def _build_chromatograms(fx: dict, channel: str = "scaled") -> dict:
    """Fixture is keyed by Common_Name strings (DNvl/DPhe BBs have no '-' so split is safe)."""
    out = {}
    for name, c in fx["chromatograms"].items():
        out[tuple(name.split("-"))] = (
            np.asarray(c["rt"], dtype=np.float64),
            np.asarray(c[channel], dtype=np.float64),
        )
    return out


def test_evaluate_library_returns_records_for_every_node():
    fx = _load_fixture()
    chroms = _build_chromatograms(fx)
    records = lcseq.evaluate_library(
        bbs_per_position=[fx["building_blocks"]] * fx["n_positions"],
        null_token=fx["null_token"],
        chromatograms=chroms,
        tolerance=TOLERANCE,
        alpha=ALPHA,
    )
    # 2 BBs, N=3, ordered (padding-invariant, order-sensitive) classes:
    # tier 0: 1 root; tier 1: 2 single-BB classes; tier 2: 2*2 = 4 ordered pairs;
    # tier 3: 2^3 = 8 compounds. Total = 15.
    assert len(records) == 15
    by_tier = {}
    for r in records:
        by_tier.setdefault(r.tier, []).append(r)
    assert sorted(by_tier) == [0, 1, 2, 3]
    assert len(by_tier[0]) == 1
    assert len(by_tier[1]) == 2
    assert len(by_tier[2]) == 4
    assert len(by_tier[3]) == 8


def test_root_and_some_descendants_pass_on_real_subset():
    """Sanity invariants on the real-data subset under the score-test consensus.

    The strict algorithm may reject some classes that earlier (looser) algorithms passed,
    so we don't assert "all 14 pass". We do assert: root passes, the tree has at least
    one tier-1 + tier-2 + tier-3 path, and any passing node has a finite consensus rt.
    """
    fx = _load_fixture()
    chroms = _build_chromatograms(fx)
    records = lcseq.evaluate_library(
        bbs_per_position=[fx["building_blocks"]] * fx["n_positions"],
        null_token=fx["null_token"],
        chromatograms=chroms,
        tolerance=TOLERANCE,
        alpha=ALPHA,
    )
    def _chosen_rt(rec) -> float | None:
        # Algorithm's chosen rt: bayesian_pick (multi-rep), then score_test_rt
        # (multi-rep prior), then initial_most_significant_picks[0] (root / n=1).
        if rec.bayesian_pick is not None:
            return rec.bayesian_pick
        if rec.score_test_rt is not None:
            return rec.score_test_rt
        return rec.initial_most_significant_picks[0] if rec.initial_most_significant_picks else None

    root = next(r for r in records if r.tier == 0)
    assert root.passed, f"root must pass: {root}"
    # Root is n=1 path: chosen rt lives in initial_most_significant_picks[0].
    assert root.initial_most_significant_picks[0] == 675.0
    root_rt = _chosen_rt(root)

    for r in records:
        if r.passed:
            chosen = _chosen_rt(r)
            assert chosen is not None and chosen >= root_rt - 1e-9

    # At least one descendant passes at each tier (a fully-pruned tree below root would
    # mean the algorithm is broken on this fixture).
    for tier in (1, 2, 3):
        passes_at_tier = sum(1 for r in records if r.tier == tier and r.passed)
        assert passes_at_tier > 0, f"no passes at tier {tier}"


def test_parent_ids_form_a_dag():
    """Every parent_id referenced must exist as some record's id."""
    fx = _load_fixture()
    chroms = _build_chromatograms(fx)
    records = lcseq.evaluate_library(
        bbs_per_position=[fx["building_blocks"]] * fx["n_positions"],
        null_token=fx["null_token"],
        chromatograms=chroms,
        tolerance=TOLERANCE,
        alpha=ALPHA,
    )
    ids = {r.id for r in records}
    for r in records:
        for pid in r.parent_ids:
            assert pid in ids, f"{r.id} references unknown parent {pid!r}"


def test_invalid_chromatogram_shape_raises():
    """Mismatched rt and intensity lengths should raise ValueError."""
    fx = _load_fixture()
    chroms = _build_chromatograms(fx)
    bad_key = next(iter(chroms))
    rt, _ = chroms[bad_key]
    chroms[bad_key] = (rt.astype(np.float64), np.array([1.0, 2.0], dtype=np.float64))
    try:
        lcseq.evaluate_library(
            bbs_per_position=[fx["building_blocks"]] * fx["n_positions"],
            null_token=fx["null_token"],
            chromatograms=chroms,
            tolerance=TOLERANCE,
            alpha=ALPHA,
        )
    except ValueError as e:
        assert "len" in str(e)
    else:
        raise AssertionError("expected ValueError on length mismatch")
