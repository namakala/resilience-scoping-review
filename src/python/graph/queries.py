"""Read-only node queries against DuckDB.

Provides get_node, get_nodes_by_type_and_tag, get_node_by_name,
get_interpretations_by_span_tag, and load_occupied_names.
Each opens a dedicated connection, ensures indexes, executes, and closes.
Results returned as plain dicts with deserialized data_json and ISO timestamps.
"""

from __future__ import annotations

from collections.abc import Set as AbstractSet
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
    tag: Optional[str],
    db_path: Optional[Path] = None,
) -> list[dict[str, Any]]:
    """All nodes matching type and (optionally) tag. Empty list if none.

    When *tag* is *None*, returns all nodes of the given type regardless
    of tag. When *tag* is a string, filters to that specific tag.
    """
    con = None
    try:
        con = _get_conn(db_path)
        if tag is not None:
            rows = con.execute(
                f"SELECT {NODE_COLUMNS} FROM nodes "
                "WHERE type = ? AND tag = ? ORDER BY id",
                [node_type, tag],
            ).fetchall()
        else:
            rows = con.execute(
                f"SELECT {NODE_COLUMNS} FROM nodes " "WHERE type = ? ORDER BY id",
                [node_type],
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


def load_occupied_names(
    entity_type: str,
    tag: Optional[str] = None,
    statuses: AbstractSet[str] | None = None,
    db_path: Optional[Path] = None,
) -> dict[str, int]:
    """Return ``{name: node_id}`` for nodes of *entity_type*.

    A generic replacement for type-specific name-lookup helpers.
    Use it to detect name collisions before creating new nodes.

    Args:
        entity_type: One of ``'code'``, ``'theme'``, ``'interpretation'``.
        tag: Ontology tag to filter by.  ``None`` = all tags.
        statuses: Status values to include.  ``None`` = all statuses.
        db_path: Optional DuckDB path.

    Returns:
        Dict mapping node name to node ID for matching nodes.
    """
    con = None
    try:
        con = _get_conn(db_path)
        if tag is not None and statuses is not None:
            placeholders = ",".join("?" for _ in statuses)
            rows = con.execute(
                f"SELECT id, name FROM nodes WHERE type = ? AND tag = ? "
                f"AND status IN ({placeholders})",
                [entity_type, tag, *statuses],
            ).fetchall()
        elif tag is not None:
            rows = con.execute(
                "SELECT id, name FROM nodes WHERE type = ? AND tag = ?",
                [entity_type, tag],
            ).fetchall()
        elif statuses is not None:
            placeholders = ",".join("?" for _ in statuses)
            rows = con.execute(
                f"SELECT id, name FROM nodes WHERE type = ? "
                f"AND status IN ({placeholders})",
                [entity_type, *statuses],
            ).fetchall()
        else:
            rows = con.execute(
                "SELECT id, name FROM nodes WHERE type = ?",
                [entity_type],
            ).fetchall()
        return {row[1]: row[0] for row in rows}
    except duckdb.Error:
        logger.exception("load_occupied_names failed")
        raise
    finally:
        if con:
            con.close()


def is_exemplar_in_any_code(
    exemplar_id: int,
    db_path: Optional[Path] = None,
) -> tuple[bool, Optional[int], Optional[str]]:
    """Check if an exemplar ID already belongs to any non-merged code node.

    Queries all ``code`` nodes with non-merged status and inspects their
    ``data_json['exemplar_ids']`` for *exemplar_id*.

    Returns:
        ``(found, code_id, code_name)`` where ``found`` is True if the
        exemplar is already linked to a code, along with that code's ID
        and name.  ``(False, None, None)`` if unclaimed.
    """
    con = None
    try:
        con = _get_conn(db_path)
        rows = con.execute(
            f"SELECT {NODE_COLUMNS} FROM nodes "
            "WHERE type = 'code' AND status != 'merged' ORDER BY id",
        ).fetchall()
        for row in rows:
            node = row_to_dict(row)
            dj = node.get("data_json") or {}
            eids = dj.get("exemplar_ids") or []
            if str(exemplar_id) in [str(e) for e in eids]:
                return True, int(node["id"]), str(node.get("name", ""))
        return False, None, None
    except duckdb.Error:
        logger.exception("is_exemplar_in_any_code failed")
        raise
    finally:
        if con:
            con.close()


def is_theme_in_any_interpretation(
    theme_id: int,
    db_path: Optional[Path] = None,
) -> tuple[bool, Optional[int], Optional[str]]:
    """Check if a theme already has a ``spans`` edge from a non-merged interpretation.

    Queries the ``edges`` table for ``spans`` edges targeting *theme_id*,
    excluding edges from interpretations with ``status = 'merged'``.

    Returns:
        ``(found, interp_id, interp_name)`` where ``found`` is True if the
        theme is already spanned by an interpretation.  ``(False, None, None)``
        if unclaimed.
    """
    con = None
    try:
        con = _get_conn(db_path)
        edges = con.execute(
            "SELECT e.source_id, n.name "
            "FROM edges e "
            "JOIN nodes n ON n.id = e.source_id "
            "WHERE e.target_id = ? AND e.edge_type = 'spans' "
            "AND n.status != 'merged'",
            [theme_id],
        ).fetchall()
        if edges:
            src_id, src_name = edges[0]
            return True, int(src_id), str(src_name)
        return False, None, None
    except duckdb.Error:
        logger.exception("is_theme_in_any_interpretation failed")
        raise
    finally:
        if con:
            con.close()
