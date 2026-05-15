"""CRUD operations for node-level result caching with pickle serialization.

Mirrors ``embedding_cache.py`` pattern. Stores serialized node outputs keyed
by ``(node_id, inputs_hash)``.  Corrupted entries are auto-deleted on
deserialization failure.
"""

from __future__ import annotations

import pickle
from typing import Any

import duckdb
from utils.logging import get_logger

logger = get_logger(__name__)


def load_cached(
    con: duckdb.DuckDBPyConnection, node_id: str, inputs_hash: str
) -> Any | None:
    """Retrieve a cached node result.

    Looks up ``node_cache`` by ``(node_id, inputs_hash)``.  If found,
    deserializes the pickle blob.  On deserialization error, deletes the
    corrupted row and returns ``None`` (miss → recompute).

    Args:
        con: Active DuckDB connection.
        node_id: Name of the Hamilton node.
        inputs_hash: Deterministic SHA-256 of the node's inputs dict.

    Returns:
        Deserialized node output if cache hit; ``None`` if missing or
        corrupted.
    """
    try:
        row = con.execute(
            "SELECT output_blob FROM node_cache "
            "WHERE node_id = ? AND inputs_hash = ?",
            [node_id, inputs_hash],
        ).fetchone()
    except Exception as exc:
        logger.error(
            "Node cache lookup failed",
            extra={"node_id": node_id, "error": str(exc)},
        )
        return None

    if row is None:
        logger.debug(
            "cache miss: no entry",
            extra={"node_id": node_id, "inputs_hash": inputs_hash},
        )
        return None

    (blob,) = row
    try:
        result = pickle.loads(blob)
        logger.debug(
            "cache hit",
            extra={"node_id": node_id, "inputs_hash": inputs_hash},
        )
        return result
    except (pickle.UnpicklingError, Exception) as exc:
        logger.warning(
            "Corrupted cache entry — deleting and rebuilding",
            extra={"node_id": node_id, "inputs_hash": inputs_hash, "error": str(exc)},
        )
        con.execute(
            "DELETE FROM node_cache WHERE node_id = ? AND inputs_hash = ?",
            [node_id, inputs_hash],
        )
        return None


def store_cached(
    con: duckdb.DuckDBPyConnection,
    node_id: str,
    inputs_hash: str,
    result: Any,
) -> None:
    """Insert or update a cached node result (upsert).

    Serializes *result* with pickle and upserts into ``node_cache``.
    On conflict, the row is replaced (last-write-wins).

    Args:
        con: Active DuckDB connection.
        node_id: Name of the Hamilton node.
        inputs_hash: Deterministic SHA-256 of the node's inputs dict.
        result: Any Python object (must be pickleable).
    """
    blob = pickle.dumps(result, protocol=pickle.HIGHEST_PROTOCOL)
    con.execute(
        "INSERT INTO node_cache (node_id, inputs_hash, output_blob) "
        "VALUES (?, ?, ?) "
        "ON CONFLICT (node_id, inputs_hash) DO UPDATE SET "
        "  output_blob = excluded.output_blob, "
        "  timestamp = DEFAULT",
        [node_id, inputs_hash, blob],
    )
    logger.debug(
        "cache stored",
        extra={"node_id": node_id, "inputs_hash": inputs_hash},
    )


def invalidate_node(con: duckdb.DuckDBPyConnection, node_id: str) -> int:
    """Remove all cached results for a given node.

    Useful when node logic or dependencies change explicitly.

    Args:
        con: Active DuckDB connection.
        node_id: Name of the Hamilton node.

    Returns:
        Number of rows deleted.
    """
    result = con.execute(
        "DELETE FROM node_cache WHERE node_id = ? RETURNING inputs_hash",
        [node_id],
    )
    rows = result.fetchall()
    count = len(rows)
    if count:
        logger.debug(
            "Node cache invalidated",
            extra={"node_id": node_id, "deleted": count},
        )
    return count


def clear_all_node_cache(con: duckdb.DuckDBPyConnection) -> int:
    """Remove every row from ``node_cache``.

    Returns:
        Number of rows deleted.
    """
    result = con.execute("DELETE FROM node_cache RETURNING node_id")
    rows = result.fetchall()
    count = len(rows)
    logger.info("All node cache entries cleared", extra={"deleted": count})
    return count
