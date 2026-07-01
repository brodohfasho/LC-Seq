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
    HelpTopic("peak_picking", "Peak picking", "peak_picking.md", ("integration", "glossary")),
    HelpTopic("integration", "Peak integration", "integration.md", ("peak_picking",)),
    HelpTopic("null_truncates", "Null truncates & BB columns", "null_truncates.md", ("lineage_analysis", "pedigree_analysis")),
    HelpTopic("lineage_analysis", "Lineage analysis", "lineage_analysis.md", ("null_truncates", "pedigree_analysis")),
    HelpTopic("pedigree_analysis", "Library pedigree (split-tree)", "pedigree_analysis.md", ("null_truncates", "lineage_analysis")),
    HelpTopic("signal_quality", "Library signal quality", "signal_quality.md", ("peak_picking", "glossary")),
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
