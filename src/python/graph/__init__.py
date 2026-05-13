"""Graph module: in-memory NetworkX graph, node/edge CRUD, and DuckDB sync.

Re-exports public API from submodules:
- singleton: get_graph, rebuild_graph
- sync: sync_node, sync_edge
- builder: build_graph (primarily for testing and advanced use cases)

The graph is constructed lazily on first access and kept in sync with the
DuckDB backend via explicit sync operations after mutations.
"""

from .builder import build_graph
from .crud import create_node
from .singleton import get_graph, rebuild_graph
from .sync import sync_edge, sync_node

__all__ = [
    "get_graph",
    "rebuild_graph",
    "sync_node",
    "sync_edge",
    "build_graph",
    "create_node",
]
