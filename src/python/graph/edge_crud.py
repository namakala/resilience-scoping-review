"""Edge CRUD operations for graph edges.

Provides single and batch edge creation into DuckDB and in-memory NetworkX.
All operations respect the dual-representation architecture (ADR-004).
"""

import json
from pathlib import Path
from typing import Any, Optional

import duckdb
from persistence.duckdb_connection import get_connection
from utils.logging import get_logger

from .exceptions import ForeignKeyError
from .singleton import get_graph
from .transactions import get_active_connection, is_in_transaction

logger = get_logger(__name__)

ALLOWED_EDGE_TYPES: frozenset[str] = frozenset(
    {
        "parent-child",
        "contains",
        "derived-from",
        "composed-of",
        "spans",
        "neighbor",
    }
)


def _validate_edge_type(edge_type: str) -> None:
    """Raise ValueError if edge_type is not in ALLOWED_EDGE_TYPES."""
    if edge_type not in ALLOWED_EDGE_TYPES:
        allowed = ", ".join(sorted(ALLOWED_EDGE_TYPES))
        raise ValueError(f"Invalid edge_type '{edge_type}'. Must be one of: {allowed}")


def _serialize_metadata(metadata: Optional[dict[str, Any]]) -> Optional[str]:
    """Serialize metadata dict to JSON string, or None. Raises ValueError on failure."""
    if metadata is None:
        return None
    try:
        return json.dumps(metadata, ensure_ascii=False)
    except (TypeError, ValueError) as e:
        raise ValueError(f"metadata_json not JSON-serializable: {e}") from e


def _check_nodes_exist(con, source_id: int, target_id: int) -> None:
    """Raise ForeignKeyError if source_id or target_id does not exist in nodes table."""
    missing = []
    for node_id in (source_id, target_id):
        if (
            con.execute(
                "SELECT 1 FROM nodes WHERE id = ? LIMIT 1", [node_id]
            ).fetchone()
            is None
        ):
            missing.append(node_id)
    if missing:
        raise ForeignKeyError(f"Node(s) not found: {missing}")


def _upsert_edge(
    con, source_id: int, target_id: int, edge_type: str, metadata_str: Optional[str]
) -> bool:
    """Insert new edge or update if endpoint merged. Returns True if updated."""
    existing = con.execute(
        "SELECT metadata_json FROM edges "
        "WHERE source_id = ? AND target_id = ? AND edge_type = ?",
        [source_id, target_id, edge_type],
    ).fetchone()

    if existing is not None:
        merged = con.execute(
            "SELECT 1 FROM nodes WHERE id IN (?, ?) AND status = 'merged' LIMIT 1",
            [source_id, target_id],
        ).fetchone()
        if merged is None:
            raise ValueError(
                f"Edge ({source_id} -> {target_id}, type='{edge_type}') already exists"
            )
        con.execute(
            "UPDATE edges SET metadata_json = ? "
            "WHERE source_id = ? AND target_id = ? AND edge_type = ?",
            [metadata_str, source_id, target_id, edge_type],
        )
        return True
    else:
        con.execute(
            "INSERT INTO edges (source_id, target_id, edge_type, metadata_json) "
            "VALUES (?, ?, ?, ?)",
            [source_id, target_id, edge_type, metadata_str],
        )
        return False


def create_edge(
    source_id: int,
    target_id: int,
    edge_type: str,
    metadata_json: Optional[dict[str, Any]] = None,
    db_path: Optional[Path] = None,
) -> None:
    """Create a labeled edge between two existing nodes.

    Args:
        source_id: Source node ID (must exist in nodes table).
        target_id: Target node ID (must exist in nodes table).
        edge_type: Relationship type from ALLOWED_EDGE_TYPES.
        metadata_json: Optional JSON-serializable metadata. None → SQL NULL.
        db_path: Path to DuckDB file. Defaults to session DB location.

    Raises:
        ValueError: Invalid edge_type, non-serializable metadata, or duplicate.
        ForeignKeyError: Source or target node does not exist.
        duckdb.Error: Database operation failure.
    """
    _validate_edge_type(edge_type)
    metadata_str = _serialize_metadata(metadata_json)

    G = get_graph(db_path)
    local_conn = False
    con = None
    try:
        if is_in_transaction():
            con = get_active_connection()
        else:
            con = get_connection(db_path)
            local_conn = True

        assert con is not None

        _check_nodes_exist(con, source_id, target_id)
        updated = _upsert_edge(con, source_id, target_id, edge_type, metadata_str)

        G.add_edge(source_id, target_id, type=edge_type, metadata=metadata_json)

        action = "Edge updated (merged node)" if updated else "Edge created"
        logger.info(
            action,
            extra={
                "source_id": source_id,
                "target_id": target_id,
                "edge_type": edge_type,
            },
        )
    except duckdb.Error as e:
        logger.error("create_edge failed", extra={"error": str(e)})
        raise
    finally:
        if local_conn and con:
            con.close()


def create_edges(
    edge_list: list[tuple[int, int, str, Optional[dict[str, Any]]]],
    db_path: Optional[Path] = None,
) -> None:
    """Create multiple edges atomically in a single transaction.

    Each tuple is (source_id, target_id, edge_type, metadata_json).
    All edge types and metadata are validated before any database writes.
    On failure, the entire transaction is rolled back.

    Args:
        edge_list: Sequence of edge definitions.
        db_path: Path to DuckDB file. Defaults to session DB location.

    Raises:
        ValueError: Invalid edge_type, metadata, or duplicate.
        ForeignKeyError: A referenced node does not exist.
        duckdb.Error: Database operation failure.
    """
    if not edge_list:
        logger.warning("create_edges called with empty list; no-op")
        return

    # Pre-validate all edge types and metadata before any DB work
    serialized = []
    for idx, (s, t, et, m) in enumerate(edge_list):
        try:
            _validate_edge_type(et)
            ms = _serialize_metadata(m)
        except ValueError as e:
            raise ValueError(f"Edge at index {idx}: {e}") from e
        serialized.append((s, t, et, ms, m))

    G = get_graph(db_path)
    local_conn = False
    con = None
    try:
        if is_in_transaction():
            con = get_active_connection()
            in_tx = True
        else:
            con = get_connection(db_path)
            local_conn = True
            in_tx = False

        assert con is not None

        if not in_tx:
            con.execute("BEGIN TRANSACTION")

        for s, t, et, ms, _ in serialized:
            _check_nodes_exist(con, s, t)
            _upsert_edge(con, s, t, et, ms)

        if not in_tx:
            con.execute("COMMIT")

        for s, t, et, _, m_dict in serialized:
            G.add_edge(s, t, type=et, metadata=m_dict)

        logger.info("Batch edges created", extra={"count": len(edge_list)})

    except (ValueError, ForeignKeyError, duckdb.Error):
        if con and not in_tx:
            try:
                con.execute("ROLLBACK")
            except duckdb.Error:
                logger.warning("create_edges: rollback failed")
        raise
    finally:
        if local_conn and con:
            con.close()
