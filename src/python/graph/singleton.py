"""Singleton lifecycle management for in-memory NetworkX graph.

Provides lazy initialization, caching, and explicit rebuild capability.
This module is responsible for graph instance management only; construction
delegates to builder.build_graph().
"""

from pathlib import Path
from typing import Optional

import networkx as nx
from persistence.duckdb_connection import get_connection
from utils.logging import get_logger

from .builder import build_graph

logger = get_logger(__name__)

# Global singleton — lazily initialized on first get_graph() call
_graph: Optional[nx.DiGraph] = None


def get_graph(db_path: Optional[Path] = None) -> nx.DiGraph:
    """Return the cached in-memory NetworkX DiGraph, building it on first call.

    The graph is constructed by querying all nodes and edges from the DuckDB
    tables 'nodes' and 'edges'. Subsequent calls return the same object
    (no rebuild) until rebuild_graph() is invoked explicitly.

    Args:
        db_path: Path to DuckDB file. Defaults to standard session DB location
            via `persistence.duckdb_connection.DEFAULT_DB_PATH`.

    Returns:
        nx.DiGraph: The in-memory directed graph with node/edge attributes.

    Raises:
        RuntimeError: If DuckDB tables are missing or malformed.
    """
    global _graph
    if _graph is None:
        con = get_connection(db_path)
        _graph = build_graph(con)
        logger.info(
            "Graph built",
            extra={
                "nodes": _graph.number_of_nodes(),
                "edges": _graph.number_of_edges(),
            },
        )
    return _graph


def rebuild_graph(db_path: Optional[Path] = None) -> nx.DiGraph:
    """Force a full rebuild of the in-memory graph, clearing any cached instance.

    Useful after bulk mutations or when explicit refresh is required. The new
    graph replaces the singleton and is returned.

    Args:
        db_path: Path to DuckDB file. Defaults to standard session DB location.

    Returns:
        nx.DiGraph: Freshly constructed graph reflecting current DB state.
    """
    global _graph
    _graph = None
    con = get_connection(db_path)
    _graph = build_graph(con)
    logger.info(
        "Graph rebuilt",
        extra={
            "nodes": _graph.number_of_nodes(),
            "edges": _graph.number_of_edges(),
        },
    )
    return _graph
