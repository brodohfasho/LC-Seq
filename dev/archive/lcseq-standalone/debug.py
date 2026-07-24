# dev/archive/lcseq-standalone/debug.py
"""Debug visualization for one equivalence class.

All algorithm-relevant values (per-rep initial earliest / most-significant /
democratic picks, score_test_rt + SE + p-value, bayesian_pick + posterior +
threshold margin, bayesian-refined per-rep picks) come from the Rust kernel via
`lcseq.diagnose_class`, so the figure shows what the algorithm actually does —
no Python re-implementation that can drift.
"""
from __future__ import annotations

from pathlib import Path
from typing import Sequence

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.lines import Line2D
from matplotlib.patches import Patch

import lcseq
from lcseq_io import parse_xlsx


def _legend_handles() -> tuple[list, list[str]]:
    """Static legend describing what every line / band / marker means. Identical
    across all panels — values (rt numbers, posteriors, margins) live in titles."""
    handles = [
        Line2D([0], [0], color="gray", alpha=0.55, linewidth=1.0, label="rep trace"),
        Line2D([0], [0], color="gray", alpha=0.25, linewidth=0.7, linestyle=":",
               label="excluded rep (no signal)"),
        Line2D([0], [0], marker="o", linestyle="none", markersize=5, color="gray",
               markeredgecolor="black", markeredgewidth=0.4,
               label="NB-significant peak"),
        Line2D([0], [0], marker="<", linestyle="none", markersize=10,
               markerfacecolor="none", markeredgecolor="black",
               label="initial earliest pick"),
        Line2D([0], [0], marker="*", linestyle="none", markersize=12,
               markerfacecolor="none", markeredgecolor="black",
               label="initial most-significant pick"),
        Line2D([0], [0], marker="D", linestyle="none", markersize=8,
               markerfacecolor="none", markeredgecolor="black",
               label="initial democratic pick"),
        Line2D([0], [0], marker="s", linestyle="none", markersize=7,
               markerfacecolor="gray", markeredgecolor="black", markeredgewidth=1.5,
               label="bayesian-refined pick (supporting: NB-sig peak in window)"),
        Line2D([0], [0], marker="s", linestyle="none", markersize=7,
               markerfacecolor="gray", markeredgecolor="black", markeredgewidth=0.4,
               label="bayesian-refined pick (no NB-sig peak; chromatogram argmax)"),
        Line2D([0], [0], marker="|", linestyle="none", markersize=14,
               markeredgewidth=2.0, color="black",
               label="initial_democratic_position"),
        Line2D([0], [0], color="red", linestyle=":", linewidth=1.5,
               label="effective_threshold"),
        Patch(facecolor="red", alpha=0.07, label="parent-exclusion (±tol)"),
        Line2D([0], [0], color="#2ca02c", linewidth=2.0,
               label="score_test_rt (multi-rep) / chosen rt (single-rep)"),
        Patch(facecolor="#2ca02c", alpha=0.10, label="score_test_rt ± SE"),
        Line2D([0], [0], color="#9467bd", linestyle="--", linewidth=2.5,
               label="bayesian_pick"),
        Patch(facecolor="#9467bd", alpha=0.10, label="bayesian_pick ± FWHM"),
    ]
    return handles, [h.get_label() for h in handles]


def plot_class(
    replicates: Sequence[tuple[np.ndarray, np.ndarray]],
    *,
    effective_threshold: float = 0.0,
    tolerance: float = 0.5,
    alpha: float = 1e-3,
    title: str = "",
    save: str | Path | None = None,
    figsize: tuple[float, float] = (12.0, 6.0),
    ax: plt.Axes | None = None,
    xlim: tuple[float, float] | None = None,
    show_legend: bool = True,
) -> plt.Figure:
    """Overlay replicates + per-rep picks + score-test prior + Bayesian pick.
    All marks come straight from Rust diagnostics — no Python re-implementation drift.

    `replicates`: iterable of (rt, intensity) numpy arrays — one per replicate.
    `effective_threshold`: parent's chosen rt; the score-test gate uses
        `vote_floor = effective_threshold + tolerance`. Drawn as red dotted line +
        pale red ±tolerance parent-exclusion band.
    `tolerance`: also sets the score-test kernel σ; FWHM = 2.355·tolerance is the
        bayesian-pick refined-match window.
    `alpha`: NB significance threshold for the picker.

    Layers (one-to-one with the algorithm's actual outputs):
      - per-rep trace: thin coloured line; small circles at every NB-significant peak.
      - per-rep initial picks (one shape per criterion, all in the rep's color):
          ◀ earliest             ★ most significant (lowest p-value)
          ◆ democratic           ■ bayesian-refined (matched to bayesian_pick within ±FWHM)
      - parent-exclusion zone: pale red ±tolerance band around `effective_threshold`.
      - score_test_rt (PRIOR center, multi-rep only): solid green line + green ±SE band.
      - bayesian_pick (ANSWER, multi-rep only): dashed purple line + purple ±FWHM band
        that coincides with where the refined squares are matched.
    """
    rep_list = [(np.asarray(rt, dtype=np.float64), np.asarray(intensity, dtype=np.float64))
                for rt, intensity in replicates]

    diag = lcseq.diagnose_class(
        [(rt, intensity) for rt, intensity in rep_list],
        effective_threshold,
        tolerance,
        alpha,
    )

    owns_figure = ax is None
    if owns_figure:
        fig, ax = plt.subplots(figsize=figsize)
    else:
        fig = ax.figure
    n_rep = len(rep_list)
    cmap = plt.get_cmap("tab10" if n_rep <= 10 else "tab20")

    excluded = set(diag.replicates_with_no_signal)

    # Per-replicate traces + significant peaks + vote markers.
    for i, (rt, intensity) in enumerate(rep_list):
        if rt.size == 0:
            continue
        c = cmap(i % cmap.N)
        is_excluded = i in excluded
        # Excluded reps drawn faint and dotted so they're visually distinguished from active.
        rep_label = f"rep {i}" if n_rep <= 12 else None
        if is_excluded and rep_label:
            rep_label += " (excluded: 0 sig peaks)"
        ax.plot(rt, intensity, color=c,
                alpha=0.25 if is_excluded else 0.55,
                linewidth=0.7 if is_excluded else 1.0,
                linestyle=":" if is_excluded else "-",
                label=rep_label)
        if is_excluded:
            continue  # excluded reps have no peaks/votes to mark
        peaks = lcseq.find_peaks(rt, intensity, alpha)
        if peaks:
            ax.plot([p.rt for p in peaks], [p.intensity for p in peaks],
                    "o", color=c, markersize=5, alpha=0.7,
                    markeredgecolor="black", markeredgewidth=0.4)
        # Marker semantics (one shape per per-rep criterion, all in the rep's color):
        #   ◀  (left triangle, open)   = initial earliest pick (smallest rt past threshold)
        #   ★  (star, open)            = initial most-significant pick (lowest p-value past threshold)
        #   ◆  (diamond, open)         = initial democratic pick (nearest broadest-agreement position)
        #   ■  (filled square)         = bayesian-refined pick (matched to bayesian_pick
        #                                within ±FWHM); black-rimmed iff the rep is in
        #                                supporting_indices.
        def _y_at(rt: float) -> float:
            return next((p.intensity for p in peaks if abs(p.rt - rt) < 1e-9), 0.0)

        earliest = (
            diag.initial_earliest_picks[i]
            if i < len(diag.initial_earliest_picks) else None
        )
        if earliest is not None:
            ax.plot(earliest, _y_at(earliest), "<", markersize=12,
                    markerfacecolor="none",
                    markeredgecolor=c, markeredgewidth=1.6, alpha=0.85)

        most_sig = (
            diag.initial_most_significant_picks[i]
            if i < len(diag.initial_most_significant_picks) else None
        )
        if most_sig is not None:
            ax.plot(most_sig, _y_at(most_sig), "*", markersize=16,
                    markerfacecolor="none",
                    markeredgecolor=c, markeredgewidth=1.6, alpha=0.85)

        democratic = (
            diag.initial_democratic_picks[i]
            if i < len(diag.initial_democratic_picks) else None
        )
        if democratic is not None:
            ax.plot(democratic, _y_at(democratic), "D", markersize=10,
                    markerfacecolor="none",
                    markeredgecolor=c, markeredgewidth=1.6, alpha=0.85)

        refined = (
            diag.bayesian_refined_picks[i]
            if i < len(diag.bayesian_refined_picks) else None
        )
        if refined is not None:
            # The refined pick is on the raw chromatogram, not necessarily at an
            # NB-significant peak. Use the chromatogram intensity at the refined
            # rt for the y-coordinate so the marker actually sits on the trace.
            y_refined = float(np.interp(refined, rt, intensity))
            in_support = i in diag.bayesian_supporting_replicates
            ax.plot(refined, y_refined, "s", color=c, markersize=8,
                    markeredgecolor="black",
                    markeredgewidth=1.5 if in_support else 0.4,
                    alpha=0.95)

    # Parent-exclusion zone: peaks within ±tolerance of `effective_threshold` are
    # rejected by the score-test gate (vote_floor = threshold + tolerance).
    ax.axvspan(
        effective_threshold - tolerance, effective_threshold + tolerance,
        color="red", alpha=0.07,
    )
    ax.axvline(effective_threshold, color="red", linestyle=":", linewidth=1.5)

    # The eclass-level "broadest-agreement position" — Stage-1 cross-rep aggregate.
    # Surfaced as a small black tick at the bottom of the panel.
    if diag.initial_democratic_position is not None:
        y_min, y_max = ax.get_ylim()
        tick_y = y_min + 0.02 * (y_max - y_min)
        ax.plot(
            diag.initial_democratic_position, tick_y,
            "|", color="black", markersize=14, markeredgewidth=2.0,
        )

    # The chosen rt for this node:
    #   - multi-rep (n_replicates_with_signal ≥ 2): score_test_rt is the prior center
    #     (green line + ±SE band); bayesian_pick is the answer (purple dashed line +
    #     ±FWHM refined-match window).
    #   - single-rep / root (n_replicates_with_signal ≤ 1): the chosen rt IS just the
    #     rep's initial_most_significant_picks[0] (green line, no SE / no Bayesian).
    is_multi_rep = diag.score_test_rt is not None and diag.bayesian_pick is not None
    single_rep_chosen: float | None = None

    if diag.score_test_rt is not None:
        if (
            is_multi_rep
            and diag.score_test_rt_se is not None
            and diag.score_test_rt_se > 0
        ):
            ax.axvspan(
                diag.score_test_rt - diag.score_test_rt_se,
                diag.score_test_rt + diag.score_test_rt_se,
                color="#2ca02c", alpha=0.10,
            )
        ax.axvline(diag.score_test_rt, color="#2ca02c", linewidth=2.0)
    elif diag.initial_most_significant_picks:
        single_rep_chosen = diag.initial_most_significant_picks[0]
        if single_rep_chosen is not None:
            ax.axvline(single_rep_chosen, color="#2ca02c", linewidth=2.0)

    if is_multi_rep:
        match_window = 2.3548 * tolerance
        ax.axvspan(
            diag.bayesian_pick - match_window,
            diag.bayesian_pick + match_window,
            color="#9467bd", alpha=0.10,
        )
        ax.axvline(
            diag.bayesian_pick, color="#9467bd", linestyle="--", linewidth=2.5,
        )

    # Title carries ALL per-panel values (rt numbers, posterior, margin, p-value,
    # rep counts, status). The legend is purely categorical, so it can be shared
    # across panels in multi-panel callers.
    if diag.insufficient_data:
        status = "INSUFFICIENT_DATA"
    elif diag.passed:
        status = "PASS"
    else:
        status = "FAIL"
    title_bits: list[str] = [
        f"n_with_signal={diag.n_replicates_with_signal}/{diag.n_replicates}",
        f"thr={effective_threshold:.3f}",
    ]
    if diag.score_test_rt is not None:
        title_bits.append(f"score_test_rt={diag.score_test_rt:.3f}")
        if diag.score_test_rt_se is not None:
            title_bits.append(f"±SE={diag.score_test_rt_se:.2f}")
    elif single_rep_chosen is not None:
        title_bits.append(f"chosen_rt={single_rep_chosen:.3f}")
    if diag.score_test_p_value is not None:
        title_bits.append(f"score_p={diag.score_test_p_value:.1e}")
    if diag.bayesian_pick is not None:
        bayes = f"bayesian_pick={diag.bayesian_pick:.3f}"
        if diag.bayesian_pick_posterior is not None:
            bayes += f" (post={diag.bayesian_pick_posterior:.2f}"
            if diag.bayesian_pick_runner_up_posterior is not None:
                bayes += f", 2nd={diag.bayesian_pick_runner_up_posterior:.2f}"
            bayes += ")"
        title_bits.append(bayes)
    if diag.bayesian_pick_threshold_margin is not None:
        title_bits.append(f"margin={diag.bayesian_pick_threshold_margin:.2f}·tol")
    if diag.initial_democratic_position is not None:
        title_bits.append(f"democ={diag.initial_democratic_position:.3f}")
    diag_str = "  ".join(title_bits)
    full_title = (
        f"{title} — {status}\n{diag_str}" if title else f"{status}\n{diag_str}"
    )
    ax.set_title(full_title, fontsize=9, loc="left")
    ax.set_xlabel("rt")
    ax.set_ylabel("intensity")
    if xlim is not None:
        ax.set_xlim(*xlim)

    if show_legend:
        handles, labels = _legend_handles()
        ax.legend(handles, labels, loc="best", fontsize=7, framealpha=0.85, ncol=1)
    ax.grid(True, alpha=0.25)
    if owns_figure:
        fig.tight_layout()
        if save is not None:
            fig.savefig(save, dpi=120, bbox_inches="tight")
    return fig


def inspect_class(
    xlsx_path: str | Path,
    class_bbs: Sequence[str],
    *,
    null_token: str = "AgxNull",
    lid: str = "DEL-0044",
    channel: str = "scaled",
    unit: str = "minutes",
    tolerance: float = 0.5,
    alpha: float = 1e-3,
    save: str | Path | None = None,
    xlim: tuple[float, float] | None = None,
) -> plt.Figure:
    """Pull all replicates of an equivalence class from the xlsx and plot.

    Runs the full `evaluate_library` first to get the algorithm's authoritative
    `effective_threshold` for this class (which includes any cassette-monotonicity
    augmentation), then passes that — not a guessed root rt — into the diagnostic.
    Without this, the viz would diverge from what the algorithm actually computed.
    """
    bbs_per_position, chroms = parse_xlsx(
        xlsx_path, lid=lid, null_token=null_token, channel=channel, unit=unit
    )
    # Equivalence: ordered N→C subsequence with nulls stripped (padding-invariant,
    # order-sensitive). `class_bbs` IS the target sequence; do not sort.
    target = list(class_bbs)
    matching = [
        chrom for positions, chrom in chroms.items()
        if [p for p in positions if p != null_token] == target
    ]
    if not matching:
        raise ValueError(f"No chromatograms found for class {list(class_bbs)} in {xlsx_path}")

    # Canonical threshold lookup: run evaluate_library and read the effective_threshold
    # from the matching node's record. No guessing.
    records = lcseq.evaluate_library(
        bbs_per_position=bbs_per_position,
        null_token=null_token,
        chromatograms=chroms,
        tolerance=tolerance,
        alpha=alpha,
    )
    target_id = "C{}_{}".format(len(target), "_".join(target))
    matched_record = next((r for r in records if r.id == target_id), None)
    if matched_record is None:
        raise ValueError(f"No record found for {target_id}")
    effective_threshold = matched_record.effective_threshold
    if effective_threshold is None:
        # Root or non-evaluated node — fall back to 0; root has no parent threshold.
        effective_threshold = 0.0

    title = (
        f"Class {{{', '.join(class_bbs)}}}  ({len(matching)} replicates)  "
        f"effective_threshold={effective_threshold:.3f}"
    )
    return plot_class(
        matching,
        effective_threshold=effective_threshold,
        tolerance=tolerance,
        alpha=alpha,
        title=title,
        save=save,
        xlim=xlim,
    )


def _class_id_for(class_bbs: Sequence[str]) -> str:
    """Build the canonical class ID the same way Rust does. The class key is the
    ordered N→C BB sequence (padding-invariant, order-sensitive); do NOT sort."""
    bbs = list(class_bbs)
    if not bbs:
        return "C0"
    return f"C{len(bbs)}_{'_'.join(bbs)}"


def _members_of_class(
    class_bbs: Sequence[str],
    chroms: dict,
    null_token: str,
) -> list[tuple[np.ndarray, np.ndarray]]:
    """All positional truncates whose non-null subsequence (N→C order, nulls stripped)
    equals `class_bbs`. Padding-invariant but order-sensitive — `[A,B]` ≠ `[B,A]`."""
    target = list(class_bbs)
    return [
        chrom for positions, chrom in chroms.items()
        if [p for p in positions if p != null_token] == target
    ]


def inspect_classes(
    xlsx_path: str | Path,
    classes: Sequence[Sequence[str]],
    *,
    null_token: str = "AgxNull",
    lid: str = "DEL-0044",
    channel: str = "scaled",
    unit: str = "minutes",
    tolerance: float = 0.5,
    alpha: float = 1e-3,
    save: str | Path | None = None,
    per_row_height: float = 3.5,
    width: float = 12.0,
    xlim: tuple[float, float] | None = None,
) -> plt.Figure:
    """Stack one panel per equivalence class, sorted top-to-bottom by tier (root → leaves).

    `classes` is a list of multisets (each multiset = list[str] of non-null BB names).
    Use `[]` for the root. Each panel uses the algorithm-canonical effective_threshold
    from a single `evaluate_library` run — no per-panel divergence.
    """
    bbs_per_position, chroms = parse_xlsx(
        xlsx_path, lid=lid, null_token=null_token, channel=channel, unit=unit
    )
    records = lcseq.evaluate_library(
        bbs_per_position=bbs_per_position,
        null_token=null_token,
        chromatograms=chroms,
        tolerance=tolerance,
        alpha=alpha,
    )
    by_id = {r.id: r for r in records}

    # Resolve each requested node → (bbs, tier, members, effective_threshold). The
    # node may be a Class (`C{tier}_...`) or a tier-N Compound (`F{N}_...`); try both.
    # Nodes not in the evaluated records (e.g. chemical-ancestor singletons that the
    # library doesn't actually contain) are silently skipped.
    panels = []
    for class_bbs in classes:
        cid_class = _class_id_for(class_bbs)
        cid_compound = (
            f"F{len(class_bbs)}_{'_'.join(class_bbs)}" if class_bbs else None
        )
        rec = by_id.get(cid_class) or (cid_compound and by_id.get(cid_compound))
        if rec is None:
            continue
        members = _members_of_class(class_bbs, chroms, null_token)
        if not members and rec.tier > 0:
            raise ValueError(f"No chromatograms found for node {list(class_bbs)}")
        # Root has no parent threshold; use 0 (root rt isn't a threshold for itself).
        eff_thr = rec.effective_threshold if rec.effective_threshold is not None else 0.0
        panels.append((class_bbs, rec.tier, members, eff_thr, rec))

    # Sort by tier ascending (root at top).
    panels.sort(key=lambda p: p[1])

    n = len(panels)
    fig, axes = plt.subplots(n, 1, figsize=(width, per_row_height * n), sharex=True)
    if n == 1:
        axes = [axes]

    for ax, (class_bbs, tier, members, eff_thr, rec) in zip(axes, panels):
        if tier == 0:
            # Root has only one member (the all-null truncate); plot it directly with
            # zero threshold (root has no parent). Root's chosen rt lives in
            # initial_most_significant_picks[0] (n=1 path).
            root_picks = rec.initial_most_significant_picks or []
            root_rt = root_picks[0] if root_picks else None
            root_rt_str = f"{root_rt:.3f}" if root_rt is not None else "—"
            label = f"tier 0  ROOT  rt={root_rt_str}"
            plot_class(members or [], effective_threshold=0.0, tolerance=tolerance,
                       alpha=alpha, title=label, ax=ax, xlim=xlim,
                       show_legend=False)
        else:
            label = (
                f"tier {tier}  {{{', '.join(class_bbs)}}}  ({len(members)} reps)"
            )
            plot_class(members, effective_threshold=eff_thr, tolerance=tolerance,
                       alpha=alpha, title=label, ax=ax, xlim=xlim,
                       show_legend=False)

    # Single shared legend off to the right of all panels.
    handles, labels = _legend_handles()
    fig.legend(
        handles, labels,
        loc="center left", bbox_to_anchor=(1.0, 0.5),
        fontsize=8, frameon=True, framealpha=0.9,
        title="legend", title_fontsize=9,
    )
    # Reserve right margin for the shared legend; tight_layout would otherwise
    # crop it. rect=(left, bottom, right, top) in figure-relative coords.
    fig.tight_layout(rect=(0.0, 0.0, 0.82, 1.0))
    if save is not None:
        fig.savefig(save, dpi=120, bbox_inches="tight")
    return fig


def inspect_lineage(
    xlsx_path: str | Path,
    leaf_class_bbs: Sequence[str],
    *,
    null_token: str = "AgxNull",
    lid: str = "DEL-0044",
    channel: str = "scaled",
    unit: str = "minutes",
    tolerance: float = 0.5,
    alpha: float = 1e-3,
    save: str | Path | None = None,
    per_row_height: float = 3.5,
    width: float = 12.0,
    xlim: tuple[float, float] | None = None,
) -> plt.Figure:
    """Stack one panel per ancestor class of `leaf_class_bbs`, root at top, leaf at bottom.

    Lineage = root + all chemical ancestors (singleton components of any cassette BB
    in the leaf's sequence, recursively) + all structural ancestors (every ordered
    subsequence reachable by removing one BB at a time, recursively) + the leaf itself.

    Equivalence is order-sensitive: `[A, B]` and `[B, A]` are distinct classes; only
    the actual N→C order from `leaf_class_bbs` is followed when enumerating ancestors.
    """
    leaf_seq = tuple(leaf_class_bbs)
    ancestors: set[tuple[str, ...]] = set()
    ancestors.add(())  # root

    # Structural ancestors: every ordered subsequence reachable by dropping one BB.
    def add_structural(seq: tuple[str, ...]) -> None:
        ancestors.add(seq)
        if not seq:
            return
        for i in range(len(seq)):
            child = seq[:i] + seq[i + 1:]
            add_structural(child)

    add_structural(leaf_seq)

    # Chemical ancestors: every cassette BB's singleton components (added as their own
    # tier-1 sequence of size 1). Apply recursively for nested cassettes.
    def add_chemical(seq: tuple[str, ...]) -> None:
        for bb in seq:
            if "-" in bb:
                for comp in bb.split("-"):
                    if (comp,) not in ancestors:
                        ancestors.add((comp,))
                        add_chemical((comp,))

    add_chemical(leaf_seq)

    classes = [list(c) for c in ancestors]
    return inspect_classes(
        xlsx_path,
        classes,
        null_token=null_token,
        lid=lid,
        channel=channel,
        unit=unit,
        tolerance=tolerance,
        alpha=alpha,
        save=save,
        per_row_height=per_row_height,
        width=width,
        xlim=xlim,
    )
