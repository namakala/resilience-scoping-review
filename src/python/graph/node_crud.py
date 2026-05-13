"""Node CRUD operations for graph nodes.

Provides atomic insertion of nodes into DuckDB and in-memory NetworkX.
All operations respect the dual-representation architecture (ADR-004).
"""

import json
from pathlib import Path
from typing import Any, Optional

import duckdb
from persistence.duckdb_connection import get_connection
from utils.logging import get_logger

from .singleton import get_graph

logger = get_logger(__name__)


def create_node(
    node_type: str,
    name: str,
    definition: str,
    tag: Optional[str],
    status: str,
    data_json: Optional[dict[str, Any]] = None,
    db_path: Optional[Path] = None,
) -> int:
    """Insert a node atomically into DuckDB and in-memory NetworkX graph.

    Args:
        node_type: One of 'code', 'theme', 'interpretation', 'tag'.
        name: Human-readable name (unique within type).
        definition: Description or narrative.
        tag: Ontology tag this node belongs to (NULL for tag nodes).
        status: Lifecycle status (draft, approved, merged, rejected, immutable).
        data_json: Optional JSON-serializable extra attributes.
        db_path: Path to DuckDB file. Defaults to session DB location.

    Returns:
        int: Auto-incremented node ID.

    Raises:
        ValueError: If (type, name) pair already exists.
        duckdb.Error: If the database operation fails.
    """
    G = get_graph(db_path)

    data_json_str = None
    if data_json is not None:
        try:
            data_json_str = json.dumps(data_json, ensure_ascii=False)
        except (TypeError, ValueError) as e:
            logger.error("data_json serialization failed", extra={"error": str(e)})
            raise ValueError(f"data_json not JSON-serializable: {e}") from e

    con = None
    try:
        con = get_connection(db_path)

        # Duplicate check: (type, name) must be unique
        row = con.execute(
            "SELECT 1 FROM nodes WHERE type = ? AND name = ? LIMIT 1",
            [node_type, name],
        ).fetchone()
        if row is not None:
            raise ValueError(f"Node {node_type}/{name} already exists")

        con.execute(
            "INSERT INTO nodes (type, name, definition, tag, status, data_json) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            [node_type, name, definition, tag, status, data_json_str],
        )

        # Retrieve auto-incremented node ID
        try:
            node_id = int(con.execute("SELECT currval('nodes_id_seq')").fetchone()[0])
        except duckdb.Error:
            node_id = int(con.execute("SELECT MAX(id) FROM nodes").fetchone()[0])

        if node_id is None:
            raise RuntimeError("Failed to retrieve node ID after insert")

        G.add_node(
            node_id,
            type=node_type,
            name=name,
            definition=definition,
            tag=tag,
            status=status,
            data_json=data_json,
        )

        logger.info(
            "Node created",
            extra={"node_id": node_id, "node_type": node_type, "node_name": name},
        )
        return node_id

    except duckdb.Error as e:
        logger.error("create_node failed", extra={"error": str(e)})
        raise
    finally:
        if con:
            con.close()
