"""Read-only node queries against DuckDB.

Provides get_node, get_nodes_by_type_and_tag, get_node_by_name,
and get_interpretations_by_span_tag.
Each opens a dedicated connection, ensures indexes, executes, and closes.
Results returned as plain dicts with deserialized data_json and ISO timestamps.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

import duckdb
from persistence.duckdb_connection import get_connection
from utils.logging import get_logger

from .query_utils import NODE_COLUMNS, ensure_indexes, row_to_dict

logger = get_logger(__name__)


def _get_conn(db_path: Optional[Path] = None) -> duckdb.DuckDBPyConnection:
    """Open connection and ensure indexes. Caller must close."""
    con = get_connection(db_path)
    ensure_indexes(con)
    return con


def get_node(
    node_id: int,
    db_path: Optional[Path] = None,
) -> dict[str, Any]:
    """Fetch a single node by primary key. Raises KeyError if not found."""
    con = None
    try:
        con = _get_conn(db_path)
        row = con.execute(
            f"SELECT {NODE_COLUMNS} FROM nodes WHERE id = ?",
            [node_id],
        ).fetchone()
        if row is None:
            raise KeyError(f"Node {node_id} not found")
        return row_to_dict(row)
    except duckdb.Error:
        logger.exception("get_node failed")
        raise
    finally:
        if con:
            con.close()


def get_nodes_by_type_and_tag(
    node_type: str,
    tag: str,
    db_path: Optional[Path] = None,
) -> list[dict[str, Any]]:
    """All nodes matching type and tag, sorted by id. Empty list if none."""
    con = None
    try:
        con = _get_conn(db_path)
        rows = con.execute(
            f"SELECT {NODE_COLUMNS} FROM nodes "
            "WHERE type = ? AND tag = ? ORDER BY id",
            [node_type, tag],
        ).fetchall()
        return [row_to_dict(r) for r in rows]
    except duckdb.Error:
        logger.exception("get_nodes_by_type_and_tag failed")
        raise
    finally:
        if con:
            con.close()


def get_node_by_name(
    name: str,
    node_type: Optional[str] = None,
    db_path: Optional[Path] = None,
) -> dict[str, Any]:
    """Fetch node by name, optionally disambiguated by type.

    Raises KeyError if not found.
    Raises LookupError if multiple matches without type filter.
    """
    con = None
    try:
        con = _get_conn(db_path)
        if node_type is not None:
            row = con.execute(
                f"SELECT {NODE_COLUMNS} FROM nodes " "WHERE name = ? AND type = ?",
                [name, node_type],
            ).fetchone()
            if row is None:
                raise KeyError(f"Node '{name}' with type '{node_type}' not found")
            return row_to_dict(row)

        rows = con.execute(
            f"SELECT {NODE_COLUMNS} FROM nodes " "WHERE name = ? ORDER BY id",
            [name],
        ).fetchall()
        if not rows:
            raise KeyError(f"Node '{name}' not found")
        if len(rows) > 1:
            raise LookupError(
                f"Multiple nodes named '{name}'. "
                f"Specify node_type to disambiguate. "
                f"Found types: {[r[1] for r in rows]}"
            )
        return row_to_dict(rows[0])
    except (KeyError, LookupError):
        raise
    except duckdb.Error:
        logger.exception("get_node_by_name failed")
        raise
    finally:
        if con:
            con.close()


def get_interpretations_by_span_tag(
    tag: str,
    db_path: Optional[Path] = None,
) -> list[dict[str, Any]]:
    """Return interpretation nodes whose ``tag_spans`` include *tag*.

    Since interpretation nodes store only ``root_tag`` in the ``tag``
    column, this function checks the ``data_json['tag_spans']`` array
    for membership. Filters in Python for correctness across DuckDB
    JSON variants.

    Args:
        tag: Ontology tag string to search for within ``tag_spans``.
        db_path: Optional DuckDB path for graph module.

    Returns:
        List of interpretation node dicts, sorted by node id.
    """
    con = None
    try:
        con = _get_conn(db_path)
        rows = con.execute(
            f"SELECT {NODE_COLUMNS} FROM nodes "
            "WHERE type = 'interpretation' ORDER BY id",
        ).fetchall()
        all_interps = [row_to_dict(r) for r in rows]

        # Filter in Python: check if tag is in data_json['tag_spans']
        result = []
        for interp in all_interps:
            dj = interp.get("data_json") or {}
            tag_spans = dj.get("tag_spans") or []
            if tag in tag_spans:
                result.append(interp)
        return result
    except duckdb.Error:
        logger.exception("get_interpretations_by_span_tag failed")
        raise
    finally:
        if con:
            con.close()
