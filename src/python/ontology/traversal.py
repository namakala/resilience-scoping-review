"""Tag ontology traversal operations: ancestors, descendants, subtree, is_ancestor.

Uses the in-memory NetworkX DAG from dag.get_tag_dag() with
functools.lru_cache for amortized O(1) lookup after cache warm-up.

When Feature 19 (DuckDB-backed traversal cache) is implemented, replace
the internal lru_cache with DuckDB-backed persistence while keeping the
public API unchanged.
"""

from functools import lru_cache
from typing import List, Set

import networkx as nx
from utils.logging import get_logger

from .dag import get_tag_dag

logger = get_logger(__name__)


def _resolve_tag(tag: str) -> None:
    """Raise KeyError if *tag* is not in the ontology DAG."""
    if tag not in get_tag_dag():
        raise KeyError(f"Unknown tag: {tag}")


@lru_cache(maxsize=None)
def _get_ancestors_cached(tag: str) -> tuple:
    """Compute ancestors ordered root -> parent.

    Returns tuple[str, ...] for hashability and caching. Excludes the
    input tag itself. Order is by depth ascending (root first, parent
    last).

    Raises:
        KeyError: If *tag* is not in the ontology DAG.
    """
    G = get_tag_dag()
    try:
        ancestors = nx.ancestors(G, tag)
    except nx.NetworkXError:
        raise KeyError(f"Unknown tag: {tag}")
    return tuple(sorted(ancestors, key=lambda t: G.nodes[t]["depth"]))


@lru_cache(maxsize=None)
def _get_descendants_cached(tag: str) -> tuple:
    """Compute descendants sorted by depth ascending.

    Returns tuple[str, ...] for hashability and caching. Excludes the
    input tag itself.

    Raises:
        KeyError: If *tag* is not in the ontology DAG.
    """
    G = get_tag_dag()
    try:
        descendants = nx.descendants(G, tag)
    except nx.NetworkXError:
        raise KeyError(f"Unknown tag: {tag}")
    return tuple(sorted(descendants, key=lambda t: G.nodes[t]["depth"]))


def get_ancestors(tag: str) -> List[str]:
    """Return all ancestors ordered root -> parent. Excludes *tag*.

    Args:
        tag: Ontology tag string (e.g. ``"Problem.Cause.Scope"``).

    Returns:
        List of ancestor tag strings. Empty for root tags.

    Raises:
        KeyError: If *tag* is not in the ontology DAG.
    """
    return list(_get_ancestors_cached(tag))


def get_descendants(tag: str) -> List[str]:
    """Return all descendants sorted by depth ascending. Excludes *tag*.

    Args:
        tag: Ontology tag string.

    Returns:
        List of descendant tag strings. Empty for leaf tags.

    Raises:
        KeyError: If *tag* is not in the ontology DAG.
    """
    return list(_get_descendants_cached(tag))


def get_subtree(tag: str) -> Set[str]:
    """Return *tag* and all its descendants (inclusive).

    Args:
        tag: Ontology tag string.

    Returns:
        Set containing *tag* and all descendants.

    Raises:
        KeyError: If *tag* is not in the ontology DAG.
    """
    _resolve_tag(tag)
    return {tag} | set(_get_descendants_cached(tag))


def is_ancestor(parent: str, child: str) -> bool:
    """Return True if *parent* is an ancestor of *child*.

    After cache warm-up this is O(1). Returns False if both tags are
    the same (a tag is not an ancestor of itself).

    Args:
        parent: Potential ancestor tag.
        child: Potential descendant tag.

    Returns:
        True if there is a directed path from *parent* to *child*.

    Raises:
        KeyError: If either tag is not in the ontology DAG.
    """
    _resolve_tag(parent)
    return parent in _get_ancestors_cached(child)


def clear_traversal_cache() -> None:
    """Clear all cached traversal results.

    Must be called after ``rebuild_tag_dag()`` or any ontology mutation
    to prevent stale results.
    """
    _get_ancestors_cached.cache_clear()
    _get_descendants_cached.cache_clear()
    logger.info("Ontology traversal cache cleared")
