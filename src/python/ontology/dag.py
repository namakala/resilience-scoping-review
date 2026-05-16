"""Tag DAG construction from ontology data.

Builds a NetworkX DiGraph from tags loaded via persistence.loaders.
Computes graph-based depth (root=0) and validates acyclicity.
Cached as a module-level singleton.
"""

from typing import Dict, Optional

import networkx as nx
import polars as pl
from graph.exceptions import CycleError
from persistence.loaders import load_tags
from utils.logging import get_logger

logger = get_logger(__name__)

_ONTOLOGY_GRAPH: Optional[nx.DiGraph] = None


def build_tag_dag() -> nx.DiGraph:
    """Construct tag DAG from ontology data loaded via load_tags().

    Reads tag, parent, description, n_contents from load_tags().
    Builds a directed graph with edges parent -> child.
    Computes depth as shortest path length from root (root=0).
    Missing parent tags are auto-inferred as empty placeholder nodes
    (description="", n_contents=0) with a warning logged. Validates
    graph is acyclic.

    Returns:
        nx.DiGraph: Tag DAG. Each node has attributes:
            tag_str (str), description (str), depth (int),
            n_contents (int).

    Raises:
        CycleError: If a cycle is detected.
    """
    tags_lf = load_tags()
    tags_df: pl.DataFrame = tags_lf.collect()

    G: nx.DiGraph = nx.DiGraph()

    if tags_df.is_empty():
        logger.info("Tag DAG built (empty)")
        return G

    # Collect sets for validation
    all_tags: set = set()
    parent_refs: set = set()

    for row in tags_df.iter_rows(named=True):
        tag = row["tag"]
        parent = row["parent"]
        description = row["description"]
        n_contents = row["n_contents"]

        G.add_node(
            tag,
            tag_str=tag,
            description=description,
            depth=0,
            n_contents=n_contents,
        )
        all_tags.add(tag)
        if parent:
            parent_refs.add(parent)

    # Infer missing parent tags as empty placeholder nodes
    missing_parents = parent_refs - all_tags
    if missing_parents:
        # Phase 1: Create placeholder nodes for all missing parents
        for missing_tag in sorted(missing_parents):
            G.add_node(
                missing_tag,
                tag_str=missing_tag,
                description="",
                depth=0,
                n_contents=0,
            )
            all_tags.add(missing_tag)

        # Phase 2: Wire each placeholder to its own parent (derived from dotted name)
        for missing_tag in sorted(missing_parents):
            parts = missing_tag.split(".")
            if len(parts) > 1:
                parent_tag = ".".join(parts[:-1])
                if parent_tag in all_tags:
                    G.add_edge(parent_tag, missing_tag)

        logger.warning(
            "Parent tag(s) not found in ontology, " "auto-inferred as empty nodes: %s",
            sorted(missing_parents),
        )

    # Add edges parent -> child
    for row in tags_df.iter_rows(named=True):
        tag = row["tag"]
        parent = row["parent"]
        if parent:
            G.add_edge(parent, tag)

    # Validate acyclicity
    _validate_acyclic(G)

    # Compute depth for each node via shortest path from roots
    depths = _compute_graph_depths(G)
    nx.set_node_attributes(G, depths, "depth")

    logger.info(
        "Tag DAG built",
        extra={
            "nodes": G.number_of_nodes(),
            "edges": G.number_of_edges(),
            "roots": sum(1 for d in depths.values() if d == 0),
        },
    )

    return G


def _validate_acyclic(G: nx.DiGraph) -> None:
    """Check G is acyclic; raise CycleError with cycle path if not.

    Args:
        G: Directed graph to validate.

    Raises:
        CycleError: If a cycle exists. Message includes cycle path.
    """
    try:
        cycle = nx.find_cycle(G)
    except nx.NetworkXNoCycle:
        return

    cycle_path = [(str(u), str(v)) for u, v in cycle]
    msg = f"Cycle detected in tag DAG: {cycle_path}"
    logger.error(msg, extra={"cycle": cycle_path})
    raise CycleError(msg)


def _compute_graph_depths(G: nx.DiGraph) -> Dict[str, int]:
    """Compute depth for each node via shortest path from root(s).

    Roots are nodes with in-degree 0. Depth is shortest path length
    from the nearest root. Cycles must be excluded before calling
    this function.

    Args:
        G: Acyclic directed graph.

    Returns:
        Dict mapping node -> depth (int). Root nodes have depth 0.
    """
    roots = [n for n in G.nodes() if G.in_degree(n) == 0]
    depths: Dict[str, int] = {}

    for root in roots:
        for node, length in nx.shortest_path_length(G, root).items():
            existing = depths.get(node)
            if existing is None or length < existing:
                depths[node] = length

    return depths


def get_tag_dag() -> nx.DiGraph:
    """Return cached tag DAG singleton, building it on first access.

    Returns:
        nx.DiGraph: The tag ontology DAG.
    """
    global _ONTOLOGY_GRAPH
    if _ONTOLOGY_GRAPH is None:
        _ONTOLOGY_GRAPH = build_tag_dag()
    return _ONTOLOGY_GRAPH


def rebuild_tag_dag() -> nx.DiGraph:
    """Force rebuild of the tag DAG singleton.

    Clears the cache and builds a fresh DAG from current ontology
    data. Useful after tag mutations or data reloads.

    Returns:
        nx.DiGraph: Freshly constructed tag DAG.
    """
    global _ONTOLOGY_GRAPH
    _ONTOLOGY_GRAPH = None
    _ONTOLOGY_GRAPH = build_tag_dag()
    logger.info("Tag DAG rebuilt")
    return _ONTOLOGY_GRAPH


def validate_tag_dag(G: Optional[nx.DiGraph] = None) -> None:
    """Validate that a given graph (or the cached DAG) is a valid DAG.

    Checks:
        - Acyclicity (raises CycleError with cycle path on failure)
        - Topological sort succeeds (verifies DAG property)

    Args:
        G: Graph to validate. Defaults to the cached singleton.

    Raises:
        CycleError: If a cycle is detected.
    """
    if G is None:
        G = get_tag_dag()
    _validate_acyclic(G)
    # Verify topological sort succeeds (confirms DAG property)
    list(nx.topological_sort(G))
    logger.info("Tag DAG validation passed")
