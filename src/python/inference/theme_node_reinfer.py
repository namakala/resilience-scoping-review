"""Re-inference helpers for theme node creation.

Provides graph-level operations needed when a theme is re-inferred:
querying existing draft themes and renaming nodes inside a transaction.

Usage:
    from inference.theme_node_reinfer import (
        load_existing_draft_themes, rename_node_raw,
    )

    draft = load_existing_draft_themes("T1")
    # -> {"ThemeName": 42}
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from graph import get_graph, get_nodes_by_type_and_tag
from graph.transactions import get_active_connection
from utils.logging import get_logger

logger = get_logger(__name__)

__all__ = ["load_existing_draft_themes", "rename_node_raw"]


def load_existing_draft_themes(
    tag: str,
    db_path: Optional[Path] = None,
) -> dict[str, int]:
    """Return ``{theme_name: node_id}`` for draft theme nodes in *tag*.

    Used to detect re-inference: a new ``ThemeInference`` with the same
    name as an existing draft theme is considered a re-generation.
    """
    nodes = get_nodes_by_type_and_tag("theme", tag, db_path=db_path)
    return {n["name"]: n["id"] for n in nodes if n.get("status") == "draft"}


def rename_node_raw(
    node_id: int,
    new_name: str,
    db_path: Optional[Path] = None,
) -> None:
    """Rename a node directly inside an active ``graph_transaction``.

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
        "Node renamed",
        extra={"node_id": node_id, "new_name": new_name},
    )
