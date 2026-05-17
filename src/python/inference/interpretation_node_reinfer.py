"""Re-synthesis helpers for interpretation node creation.

Provides graph-level operations needed when an interpretation is
re-synthesized: renaming a node inside a transaction.

Usage:
    from inference.interpretation_node_reinfer import rename_node_raw
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from graph import get_graph
from graph.transactions import get_active_connection
from utils.logging import get_logger

logger = get_logger(__name__)

__all__ = ["rename_node_raw"]


def rename_node_raw(
    node_id: int,
    new_name: str,
    db_path: Optional[Path] = None,
) -> None:
    """Rename a node inside an active ``graph_transaction``.

    Updates both the DuckDB ``nodes`` table and the in-memory NetworkX
    graph.  Must only be called from within a :class:`graph_transaction`
    context; raises ``RuntimeError`` otherwise.
    """
    con = get_active_connection()
    if con is None:
        raise RuntimeError("rename_node_raw must be called inside a graph_transaction")
    con.execute("UPDATE nodes SET name = ? WHERE id = ?", [new_name, node_id])
    G = get_graph(db_path)
    if node_id in G:
        G.nodes[node_id]["name"] = new_name
    logger.info(
        "Interpretation node renamed",
        extra={"node_id": node_id, "new_name": new_name},
    )
