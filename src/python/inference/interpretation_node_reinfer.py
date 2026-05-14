"""Re-synthesis helpers for interpretation node creation.

Provides graph-level operations needed when an interpretation is
re-synthesized: querying existing draft interpretations across all
tags and renaming nodes inside a transaction.

Usage:
    from inference.interpretation_node_reinfer import (
        load_existing_draft_interpretations, rename_node_raw,
    )

    drafts = load_existing_draft_interpretations()
    # -> {"InterpretationName": 42}
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from graph import get_graph
from graph.transactions import get_active_connection
from persistence.duckdb_connection import get_connection
from utils.logging import get_logger

logger = get_logger(__name__)

__all__ = ["load_existing_draft_interpretations", "rename_node_raw"]


def load_existing_draft_interpretations(
    db_path: Optional[Path] = None,
) -> dict[str, int]:
    """Return ``{interpretation_name: node_id}`` for all draft interpretation nodes.

    Queries across all tags since interpretations span multiple tags and
    their ``tag`` column stores only the root tag.
    """
    con = get_connection(db_path)
    try:
        rows = con.execute(
            "SELECT id, name FROM nodes "
            "WHERE type = 'interpretation' AND status = 'draft'"
        ).fetchall()
        return {row[1]: row[0] for row in rows}
    finally:
        con.close()


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
