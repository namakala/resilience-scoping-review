"""Tag-span computation helpers for interpretation node creation.

Provides :func:`compute_tag_spans` to resolve theme IDs to their
ontology tags, and :func:`compute_root_tag` to find the minimum-depth
tag (closest to root) in a tag set.

Usage:
    from inference.interpretation_tag_utils import (
        compute_root_tag, compute_tag_spans,
    )

    spans = compute_tag_spans(interpretations)
    root = compute_root_tag({"T1", "T2"})
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from graph import get_node
from ontology import get_tag_dag
from utils.logging import get_logger

from .parsing import InterpretationInference

logger = get_logger(__name__)

__all__ = ["compute_root_tag", "compute_tag_spans"]


def compute_tag_spans(
    interpretations: list[InterpretationInference],
    db_path: Optional[Path] = None,
) -> dict[str, tuple[set[str], str]]:
    """Resolve theme IDs to tags, return ``{name: (tag_set, root_tag)}``.

    Raises ``KeyError`` if any theme ID does not exist.
    """
    result: dict[str, tuple[set[str], str]] = {}
    for interp in interpretations:
        theme_tags: set[str] = set()
        for tid_str in interp.theme_ids:
            try:
                theme = get_node(int(tid_str), db_path=db_path)
            except (KeyError, ValueError):
                raise KeyError(
                    f"Theme ID '{tid_str}' not found for interpretation "
                    f"'{interp.interpretation_name}'"
                )
            t_tag = theme.get("tag")
            if t_tag:
                theme_tags.add(t_tag)
        root_tag = compute_root_tag(theme_tags)
        result[interp.interpretation_name] = (theme_tags, root_tag)
    return result


def compute_root_tag(tag_spans: set[str]) -> str:
    """Return the tag with minimum depth in the ontology DAG.

    The root of a contiguous span is the tag closest to the ontology root.
    Falls back to the first tag (sorted) if depth info is unavailable.
    """
    if not tag_spans:
        return ""
    if len(tag_spans) == 1:
        return next(iter(tag_spans))
    try:
        dag = get_tag_dag()
        return min(
            tag_spans,
            key=lambda t: dag.nodes[t].get("depth", 0) if t in dag else 0,
        )
    except Exception:
        logger.warning("Could not compute root tag; using first tag in span")
        return sorted(tag_spans)[0]
