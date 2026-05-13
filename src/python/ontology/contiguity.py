"""Contiguous subtree check for interpretation tag_spans.

Standalone module — no imports from sibling ontology modules. Shared
with Feature 50 (multi-tag-span-validation).
"""

from typing import Optional, Set

import networkx as nx

__all__ = ["is_contiguous_subtree"]


def _resolve_tag_dag(tag_dag: Optional[nx.DiGraph] = None) -> nx.DiGraph:
    """Return *tag_dag* or the singleton ontology DAG."""
    if tag_dag is not None:
        return tag_dag
    from .dag import get_tag_dag

    return get_tag_dag()


def is_contiguous_subtree(
    tags: Set[str],
    tag_dag: Optional[nx.DiGraph] = None,
) -> bool:
    """Return True when *tags* form a connected, downward-closed subtree.

    A set of tags is contiguous when every tag on the shortest DAG path
    between the LCA (lowest common ancestor) and each member is also in
    the set. A single tag or empty set is trivially contiguous.

    Args:
        tags: Set of ontology tag strings.
        tag_dag: Ontology DAG. Defaults to the singleton.

    Returns:
        True if tags form a contiguous subtree in the ontology.
    """
    dag = _resolve_tag_dag(tag_dag)
    if len(tags) <= 1:
        return True

    chains: list[set[str]] = []
    for t in tags:
        ancestors = set(nx.ancestors(dag, t))
        ancestors.add(t)
        chains.append(ancestors)

    common = set.intersection(*chains) if chains else set()
    if not common:
        return False

    lca: str = max(common, key=lambda t: dag.nodes[t].get("depth", 0))

    for t in tags:
        try:
            path = nx.shortest_path(dag, lca, t)
        except (nx.NetworkXNoPath, nx.NodeNotFound):
            return False
        for node in path[1:-1]:
            if node not in tags:
                return False

    return True


def _missing_intermediates(
    tags: Set[str],
    tag_dag: Optional[nx.DiGraph] = None,
) -> Set[str]:
    """Return set of tags missing for contiguity. Empty = contiguous."""
    dag = _resolve_tag_dag(tag_dag)
    if len(tags) <= 1:
        return set()

    chains = [set(nx.ancestors(dag, t)) | {t} for t in tags]
    common = set.intersection(*chains) if chains else set()
    if not common:
        return set()

    lca: str = max(common, key=lambda t: dag.nodes[t].get("depth", 0))
    missing: set[str] = set()
    for t in tags:
        try:
            path = nx.shortest_path(dag, lca, t)
        except (nx.NetworkXNoPath, nx.NodeNotFound):
            return tags
        for node in path[1:-1]:
            if node not in tags:
                missing.add(node)
    return missing
