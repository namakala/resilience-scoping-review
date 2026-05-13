"""Graph traversal utilities: children, parents, successors, predecessors, path.

Provides read-only traversal operations on the in-memory NetworkX DiGraph.
Wraps NetworkX functions with cache management and cycle detection.
"""

import functools
from pathlib import Path
from typing import Optional

import networkx as nx
from utils.logging import get_logger

from .exceptions import CycleError
from .singleton import get_graph

logger = get_logger(__name__)

# Module-level flag: None = unchecked, True/False = cached acyclicity result
_graph_is_acyclic: Optional[bool] = None


def _assert_acyclic(G: nx.DiGraph) -> None:
    """Raise CycleError if the graph contains a directed cycle.

    Result cached to avoid O(V+E) check on every call. Reset by
    clear_traversal_cache().
    """
    global _graph_is_acyclic
    if _graph_is_acyclic is None:
        _graph_is_acyclic = nx.is_directed_acyclic_graph(G)
        if not _graph_is_acyclic:
            logger.error("Cycle detected in graph; tag hierarchy must be a DAG")
    if not _graph_is_acyclic:
        raise CycleError("Graph contains a cycle; tag hierarchy must be a DAG")


def clear_traversal_cache() -> None:
    """Clear all cached traversal results and the cycle-detection flag.

    Must be called after any graph mutation (sync_node, sync_edge, or
    rebuild_graph) to prevent stale results from being returned.
    """
    global _graph_is_acyclic
    _graph_is_acyclic = None
    get_children.cache_clear()
    get_parents.cache_clear()
    get_successors.cache_clear()
    get_predecessors.cache_clear()
    get_path.cache_clear()


@functools.lru_cache(maxsize=128)
def get_children(
    node_id: int,
    db_path: Optional[Path] = None,
) -> list[int]:
    """Return immediate 1-hop children (direct successors) of *node_id*.

    Args:
        node_id: Target node ID.
        db_path: DuckDB path for graph initialization (default: session DB).

    Returns:
        Sorted list of child node IDs. Empty if no children.

    Raises:
        nx.NetworkXError: If *node_id* is not in the graph.
    """
    G = get_graph(db_path)
    return sorted(G.successors(node_id))


@functools.lru_cache(maxsize=128)
def get_parents(
    node_id: int,
    db_path: Optional[Path] = None,
) -> list[int]:
    """Return immediate 1-hop parents (direct predecessors) of *node_id*.

    Args:
        node_id: Target node ID.
        db_path: DuckDB path for graph initialization (default: session DB).

    Returns:
        Sorted list of parent node IDs. Empty if no parents (root).

    Raises:
        nx.NetworkXError: If *node_id* is not in the graph.
    """
    G = get_graph(db_path)
    return sorted(G.predecessors(node_id))


@functools.lru_cache(maxsize=128)
def get_successors(
    node_id: int,
    db_path: Optional[Path] = None,
) -> list[int]:
    """Return all descendants (transitive closure) reachable from *node_id*.

    Checks the graph is acyclic first; raises CycleError if not.

    Args:
        node_id: Target node ID.
        db_path: DuckDB path for graph initialization (default: session DB).

    Returns:
        Sorted list of descendant node IDs. Empty if leaf.

    Raises:
        CycleError: If the graph contains a directed cycle.
        nx.NetworkXError: If *node_id* is not in the graph.
    """
    G = get_graph(db_path)
    _assert_acyclic(G)
    return sorted(nx.descendants(G, node_id))


@functools.lru_cache(maxsize=128)
def get_predecessors(
    node_id: int,
    db_path: Optional[Path] = None,
) -> list[int]:
    """Return all ancestors (transitive closure) that can reach *node_id*.

    Checks the graph is acyclic first; raises CycleError if not.

    Args:
        node_id: Target node ID.
        db_path: DuckDB path for graph initialization (default: session DB).

    Returns:
        Sorted list of ancestor node IDs. Empty if root.

    Raises:
        CycleError: If the graph contains a directed cycle.
        nx.NetworkXError: If *node_id* is not in the graph.
    """
    G = get_graph(db_path)
    _assert_acyclic(G)
    return sorted(nx.ancestors(G, node_id))


@functools.lru_cache(maxsize=128)
def get_path(
    source_id: int,
    target_id: int,
    db_path: Optional[Path] = None,
) -> Optional[list[int]]:
    """Return shortest directed path from *source_id* to *target_id*.

    Path includes both endpoints. Returns None when no path exists
    (e.g. disconnected components or target upstream of source).

    Args:
        source_id: Starting node ID.
        target_id: Target node ID.
        db_path: DuckDB path for graph initialization (default: session DB).

    Returns:
        List of node IDs forming the shortest path, or None.

    Raises:
        CycleError: If the graph contains a directed cycle.
        nx.NetworkXError: If either node is not in the graph.
    """
    G = get_graph(db_path)
    _assert_acyclic(G)
    try:
        return nx.shortest_path(  # type: ignore[no-any-return]
            G, source=source_id, target=target_id
        )
    except nx.NetworkXNoPath:
        return None
