"""Pure DAG functions for grouping ready tags into contiguous subtrees.

Provides :func:`group_ready_tags_into_spans` for discovering contiguous
tag clusters, :func:`build_tag_hierarchy` and :func:`build_ontology_subtree`
for prompt context generation.

All functions are pure — no DB dependency, operate on NetworkX DiGraph.

Usage:
    from inference.interpretation_span_grouping import (
        group_ready_tags_into_spans,
        build_tag_hierarchy,
        build_ontology_subtree,
    )

    spans = group_ready_tags_into_spans({"A", "A.B", "A.C"})
    hierarchy = build_tag_hierarchy({"A", "A.B"})
    subtree = build_ontology_subtree({"A", "A.B", "A.C"})
"""

from __future__ import annotations

from typing import List, Optional, Set

import networkx as nx
from ontology import is_contiguous_subtree
from utils.logging import get_logger

logger = get_logger(__name__)

__all__ = [
    "build_tag_hierarchy",
    "build_ontology_subtree",
    "group_ready_tags_into_spans",
]


def _resolve_dag(tag_dag: Optional[nx.DiGraph] = None) -> nx.DiGraph:
    """Return *tag_dag* or the singleton ontology DAG."""
    if tag_dag is not None:
        return tag_dag
    from ontology.dag import get_tag_dag

    return get_tag_dag()


def group_ready_tags_into_spans(
    ready_tags: Set[str],
    tag_dag: Optional[nx.DiGraph] = None,
) -> List[Set[str]]:
    """Partition *ready_tags* into contiguous subtree spans.

    Uses the ontology DAG to find weakly connected components in the
    subgraph induced by *ready_tags*. Each component is validated via
    :func:`~ontology.is_contiguous_subtree`. Components with fewer
    than 2 tags are discarded.

    Args:
        ready_tags: Set of interpretation-ready tag names.
        tag_dag: Ontology DAG. Defaults to the singleton.

    Returns:
        List of tag sets, each forming a contiguous subtree with ≥2 tags.
    """
    dag = _resolve_dag(tag_dag)
    if len(ready_tags) < 2:
        return []

    induced = dag.subgraph(ready_tags)
    components = list(nx.weakly_connected_components(induced))

    spans: list[set[str]] = []
    for comp in components:
        if len(comp) < 2:
            continue
        if not is_contiguous_subtree(comp, tag_dag):
            logger.warning(
                "Ready-tag component %s is not a contiguous subtree; skipping",
                sorted(comp),
            )
            continue
        spans.append(comp)
        logger.debug("Found contiguous span: %s", sorted(comp))

    if not spans:
        logger.info("No contiguous tag spans with ≥2 tags found")
    return spans


def build_tag_hierarchy(
    span_tags: Set[str],
    tag_dag: Optional[nx.DiGraph] = None,
) -> List[List[str]]:
    """Build ``tag_hierarchy`` for the interpretation prompt.

    For each tag in *span_tags*, returns its ancestor chain from root
    to the tag itself. Order is deterministic (sorted by tag name).

    Returns:
        List of paths, e.g. ``[["root", "A", "A.B"], ["root", "A", "A.C"]]``.
    """
    dag = _resolve_dag(tag_dag)

    hierarchy: list[list[str]] = []
    for tag in sorted(span_tags):
        ancestors = sorted(
            nx.ancestors(dag, tag),
            key=lambda t: dag.nodes[t].get("depth", 0) if t in dag else 0,
        )
        hierarchy.append(ancestors + [tag])
    return hierarchy


def build_ontology_subtree(
    span_tags: Set[str],
    tag_dag: Optional[nx.DiGraph] = None,
) -> str:
    """Build an indented ontology subtree diagram for the interpretation prompt.

    Produces a string like::

        root
          A
            A.B
            A.C

    Uses the induced subgraph of *span_tags* from the ontology DAG.
    Falls back to a flat bullet list if the subgraph has no edges.
    """
    dag = _resolve_dag(tag_dag)
    if not span_tags:
        return ""

    induced = dag.subgraph(span_tags)
    roots = [n for n in induced.nodes() if induced.in_degree(n) == 0]

    if not roots:
        return "\n".join(f"- {t}" for t in sorted(span_tags))

    lines: list[str] = []

    def _dfs(node: str, depth: int) -> None:
        lines.append("  " * depth + node)
        for child in sorted(induced.successors(node)):
            _dfs(child, depth + 1)

    for root in sorted(roots):
        _dfs(root, 0)

    return "\n".join(lines)
