"""Explicit synchronization: keep in-memory graph in sync with DuckDB.

Provides targeted update operations for individual nodes and edges after
external mutations. Intended to be called by persistence layer and HITL
mutation handlers following any INSERT/UPDATE/DELETE operation.
"""

import json
from pathlib import Path
from typing import Optional

import duckdb
from utils.logging import get_logger

from .singleton import get_graph

logger = get_logger(__name__)


def sync_node(node_id: int, db_path: Optional[Path] = None) -> None:
    """Update or insert a single node in the in-memory graph from DuckDB.

    After a node mutation via persistence API, call this function to keep the
    in-memory graph synchronized. No-op if node does not exist in DB; logs
    warning. Errors are logged but do not raise.

    Args:
        node_id: Primary key of the node to sync.
        db_path: Path to DuckDB file. Defaults to standard session DB location.
    """
    G = get_graph(db_path)
    from persistence.duckdb_connection import get_connection

    con = None
    try:
        con = get_connection(db_path)
        row = con.execute(
            "SELECT type, name, definition, tag, status FROM nodes WHERE id = ?",
            [node_id],
        ).fetchone()

        if row is None:
            logger.warning(
                "sync_node: node not found in nodes table",
                extra={"node_id": node_id},
            )
            return

        attrs = {
            "type": row[0],
            "name": row[1],
            "definition": row[2],
            "tag": row[3],
            "status": row[4],
        }
        G.add_node(node_id, **attrs)
        logger.debug("Node synced into graph", extra={"node_id": node_id})

    except duckdb.Error as e:
        logger.error(
            "sync_node: query failed",
            extra={"node_id": node_id, "error": str(e)},
        )
    finally:
        if con:
            con.close()


def sync_edge(
    source_id: int,
    target_id: int,
    edge_type: str,
    db_path: Optional[Path] = None,
) -> None:
    """Update or insert a single edge in the in-memory graph from DuckDB.

    After an edge mutation via persistence API, call this to synchronize the
    graph. The composite key is (source_id, target_id, edge_type). No-op if
    edge does not exist; logs warning. Errors are logged but do not raise.

    Args:
        source_id: Source node ID.
        target_id: Target node ID.
        edge_type: Edge type string (e.g., 'contains', 'derived-from').
        db_path: Path to DuckDB file. Defaults to standard session DB location.
    """
    G = get_graph(db_path)
    from persistence.duckdb_connection import get_connection

    con = None
    try:
        con = get_connection(db_path)
        row = con.execute(
            "SELECT metadata_json FROM edges WHERE source_id = ? AND target_id = ? "
            "AND edge_type = ?",
            [source_id, target_id, edge_type],
        ).fetchone()

        if row is None:
            logger.warning(
                "sync_edge: edge not found in edges table",
                extra={
                    "source_id": source_id,
                    "target_id": target_id,
                    "edge_type": edge_type,
                },
            )
            return

        metadata_json = row[0]
        metadata = None
        if metadata_json is not None:
            try:
                metadata = json.loads(metadata_json)
            except (json.JSONDecodeError, TypeError) as e:
                logger.warning(
                    "Failed to parse edge metadata_json; storing raw",
                    extra={
                        "edge": (source_id, target_id, edge_type),
                        "error": str(e),
                    },
                )
                metadata = metadata_json

        G.add_edge(
            source_id,
            target_id,
            type=edge_type,
            metadata=metadata,
        )
        logger.debug(
            "Edge synced into graph",
            extra={
                "source_id": source_id,
                "target_id": target_id,
                "edge_type": edge_type,
            },
        )

    except duckdb.Error as e:
        logger.error(
            "sync_edge: query failed",
            extra={
                "source_id": source_id,
                "target_id": target_id,
                "edge_type": edge_type,
                "error": str(e),
            },
        )
    finally:
        if con:
            con.close()
