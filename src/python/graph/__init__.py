"""Graph module: in-memory NetworkX graph, node/edge CRUD, and DuckDB sync.

Re-exports public API from submodules:
- node_crud: create_node
- edge_crud: create_edge, create_edges
- singleton: get_graph, rebuild_graph
- sync: sync_node, sync_edge
- traversal: get_children, get_parents, get_successors, get_predecessors, get_path
- builder: build_graph (primarily for testing and advanced use cases)

The graph is constructed lazily on first access and kept in sync with the
DuckDB backend via explicit sync operations after mutations.
"""

from .builder import build_graph
from .edge_crud import create_edge, create_edges
from .exceptions import CycleError, ForeignKeyError
from .node_crud import create_node
from .queries import (
    get_interpretations_by_span_tag,
    get_node,
    get_node_by_name,
    get_nodes_by_type_and_tag,
)
from .singleton import get_graph, rebuild_graph
from .sync import sync_edge, sync_node
from .transactions import GraphTransactionError, graph_transaction
from .traversal import (
    clear_traversal_cache,
    get_children,
    get_parents,
    get_path,
    get_predecessors,
    get_successors,
)

__all__ = [
    "get_graph",
    "rebuild_graph",
    "sync_node",
    "sync_edge",
    "build_graph",
    "create_node",
    "create_edge",
    "create_edges",
    "get_node",
    "get_nodes_by_type_and_tag",
    "get_node_by_name",
    "get_interpretations_by_span_tag",
    "ForeignKeyError",
    "CycleError",
    "GraphTransactionError",
    "graph_transaction",
    "get_children",
    "get_parents",
    "get_successors",
    "get_predecessors",
    "get_path",
    "clear_traversal_cache",
]
