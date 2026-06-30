"""Render the pruned pedigree tree as a graphviz figure.

Accepts any iterable of records exposing the attributes set by `lcseq.evaluate_library`:
    id, label, tier, kind ("class" | "compound"), parent_ids, evaluated, passed,
    insufficient_data, bayesian_pick, score_test_rt, initial_most_significant_picks.
"""
from __future__ import annotations

from pathlib import Path
from typing import Iterable, Protocol

import graphviz


class _RecordLike(Protocol):
    id: str
    label: str
    tier: int
    kind: str
    parent_ids: list[str]
    evaluated: bool
    passed: bool
    insufficient_data: bool
    bayesian_pick: float | None
    score_test_rt: float | None
    initial_most_significant_picks: list[float | None]


# Fill colours by node kind/state.
_COLOR_ROOT = "#d0d0d0"               # grey — the foundation node
_COLOR_CLASS = "#cfe8cf"              # light green — passed class
_COLOR_COMPOUND = "#a6d8a6"           # deeper green — passed compound
_COLOR_FAILED = "#e57373"             # red — synthesis-style failure (signal exists,
                                      # no peak past parent)
_COLOR_INSUFFICIENT_DATA = "#fce8a3"  # pale yellow — every rep was a sequencing
                                      # failure; not a synthesis failure


def _node_color(record: "_RecordLike") -> str:
    if record.tier == 0:
        return _COLOR_ROOT
    if record.passed:
        return _COLOR_COMPOUND if record.kind == "compound" else _COLOR_CLASS
    # Distinguish sequencing failure (no usable data) from synthesis failure.
    if getattr(record, "insufficient_data", False):
        return _COLOR_INSUFFICIENT_DATA
    return _COLOR_FAILED


def render_pruned_tree(
    records: Iterable[_RecordLike],
    out_path: str | Path,
    *,
    fmt: str = "png",
    layout: str = "twopi",
    include_failed: bool = True,
    show_rt: bool = True,
    keep_dot: bool = False,
) -> Path:
    """Render the pedigree to a graphviz file.

    Colour scheme:
      - root → grey (the foundation node)
      - passed class → light green
      - passed compound → deeper green
      - synthesis failure (signal present, no peak past parent) → red
      - sequencing failure (every rep had zero NB-significant peaks) → pale yellow

    Failed nodes are the boundary between the passed subtree and the pruned subtree.
    Distinguishing synthesis failures (red) from sequencing failures / insufficient
    data (yellow) tells the reader whether the chemistry didn't yield a product or
    whether the data simply can't support a call. Gate-pruned descendants (children
    of a failed node) are never rendered.

    Parameters
    ----------
    records :
        Output of `lcseq.evaluate_library` (or any iterable of equivalent record objects).
    out_path :
        Output path WITHOUT a format extension; graphviz appends one (e.g. `tree` → `tree.png`).
    fmt :
        Image format passed to graphviz ("png", "svg", "pdf", ...).
    layout :
        Graphviz layout engine. `"twopi"` puts the root at the centre with tier rings;
        `"dot"` produces a top-down hierarchy.
    include_failed :
        If True (default), include evaluated-but-failed nodes (the trim points) as red.
        If False, render only the passed subtree.
    show_rt :
        Append the algorithm's chosen rt to passing-node labels.
    keep_dot :
        If True, leave the intermediate `.dot` source file next to the output.

    Returns
    -------
    Path to the rendered image file.
    """
    out_path = Path(out_path)
    g = graphviz.Digraph(
        name=out_path.stem,
        engine=layout,
        graph_attr={"overlap": "false", "splines": "true", "bgcolor": "white"},
        node_attr={"shape": "ellipse", "style": "filled", "fontname": "Helvetica"},
        edge_attr={"color": "#888888"},
    )

    visible = {r.id: r for r in records if r.passed or (include_failed and r.evaluated)}

    def _chosen_rt(rec) -> float | None:
        # The algorithm's chosen rt: bayesian_pick (multi-rep), then score_test_rt
        # (multi-rep with no Bayesian candidates), then the n=1 / root single pick.
        if rec.bayesian_pick is not None:
            return rec.bayesian_pick
        if rec.score_test_rt is not None:
            return rec.score_test_rt
        picks = rec.initial_most_significant_picks or []
        return picks[0] if picks else None

    for r in visible.values():
        label = r.label
        if show_rt and r.passed:
            chosen = _chosen_rt(r)
            if chosen is not None:
                label = f"{r.label}\\nrt={chosen:.1f}"
        g.node(r.id, label=label, fillcolor=_node_color(r))

    for r in visible.values():
        for pid in r.parent_ids:
            if pid in visible:
                g.edge(pid, r.id)

    rendered = g.render(out_path.with_suffix(""), format=fmt, cleanup=not keep_dot)
    return Path(rendered)
