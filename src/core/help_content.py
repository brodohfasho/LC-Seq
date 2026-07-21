# src/core/help_content.py
"""
Load bundled scientist help topics for the in-app help viewer.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Optional, Tuple

_HELP_DIR = Path(__file__).resolve().parent.parent / "help"


@dataclass(frozen=True)
class HelpTopic:
    """One help article."""

    topic_id: str
    title: str
    filename: str
    related: Tuple[str, ...] = ()


HELP_TOPICS: Tuple[HelpTopic, ...] = (
    HelpTopic(
        "library_analysis",
        "Library Analysis overview",
        "library_analysis.md",
        ("del_library_setup", "signal_quality", "pedigree_analysis", "del_cycle_bundle_glossary"),
    ),
    HelpTopic(
        "del_library_setup",
        "DEL library setup",
        "del_library_setup.md",
        ("null_truncates", "library_analysis", "pedigree_analysis"),
    ),
    HelpTopic(
        "null_truncates",
        "Null truncates & BB columns",
        "null_truncates.md",
        ("del_library_setup", "lineage_analysis", "pedigree_analysis"),
    ),
    HelpTopic("peak_picking", "Peak picking", "peak_picking.md", ("glossary", "library_analysis")),
    HelpTopic(
        "lineage_analysis",
        "Lineage analysis",
        "lineage_analysis.md",
        ("null_truncates", "pedigree_analysis", "peak_picking"),
    ),
    HelpTopic(
        "pedigree_analysis",
        "Library pedigree analysis",
        "pedigree_analysis.md",
        ("null_truncates", "lineage_analysis", "pedigree_split_tree", "del_cycle_bundle_glossary", "library_analysis"),
    ),
    HelpTopic(
        "pedigree_split_tree",
        "Pedigree visualization figure",
        "pedigree_split_tree_readme.md",
        ("pedigree_analysis", "del_cycle_bundle_glossary"),
    ),
    HelpTopic(
        "del_cycle_bundle_glossary",
        "Export analysis bundle glossary",
        "del_cycle_bundle_glossary.md",
        ("pedigree_analysis", "library_analysis", "pedigree_split_tree"),
    ),
    HelpTopic(
        "signal_quality",
        "Library signal quality",
        "signal_quality.md",
        ("peak_picking", "library_analysis", "glossary"),
    ),
    HelpTopic("glossary", "Glossary", "glossary.md", ()),
)

_TOPIC_BY_ID: Dict[str, HelpTopic] = {t.topic_id: t for t in HELP_TOPICS}


def list_help_topics() -> List[HelpTopic]:
    """Return all help topics in display order."""
    return list(HELP_TOPICS)


def get_help_topic(topic_id: str) -> Optional[HelpTopic]:
    return _TOPIC_BY_ID.get(topic_id)


@lru_cache(maxsize=32)
def load_help_text(topic_id: str) -> str:
    """Load help body text for a topic id."""
    topic = get_help_topic(topic_id)
    if topic is None:
        return f"Unknown help topic: {topic_id}"
    path = _HELP_DIR / topic.filename
    if not path.is_file():
        return f"Help file missing: {path.name}"
    return path.read_text(encoding="utf-8")


def format_help_with_related(topic_id: str) -> str:
    """Return topic body plus a short related-topics footer."""
    body = load_help_text(topic_id)
    topic = get_help_topic(topic_id)
    if topic is None or not topic.related:
        return body
    lines = [body.rstrip(), "", "— Related topics —"]
    for related_id in topic.related:
        related = get_help_topic(related_id)
        if related:
            lines.append(f"• {related.title} ({related_id})")
    return "\n".join(lines)
