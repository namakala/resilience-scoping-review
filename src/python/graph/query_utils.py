"""Shared utilities for node query operations.

Provides the column constant, DuckDB index management, and row-to-dict
conversion used by queries.py and potentially other query modules.
"""

import json
from typing import Any, Optional

import duckdb
from utils.logging import get_logger

logger = get_logger(__name__)

NODE_COLUMNS: str = (
    "id, type, name, definition, tag, status, " "data_json, created_at, updated_at"
)

_indexes_created: bool = False


def ensure_indexes(con: duckdb.DuckDBPyConnection) -> None:
    """Create composite index on nodes(type, tag) if not yet present.

    Idempotent via module-level flag to avoid repeated DDL round-trips.
    """
    global _indexes_created
    if not _indexes_created:
        con.execute(
            "CREATE INDEX IF NOT EXISTS idx_nodes_type_tag " "ON nodes(type, tag)"
        )
        logger.debug("Index idx_nodes_type_tag created / verified")
        _indexes_created = True


def row_to_dict(row: tuple) -> dict[str, Any]:
    """Convert a DuckDB node row tuple into a dictionary.

    Unpacks the 9-element tuple, deserializes ``data_json`` from JSON
    string, and converts timestamps to ISO strings.
    """
    (
        node_id,
        node_type,
        name,
        definition,
        tag,
        status,
        data_json_str,
        created_at,
        updated_at,
    ) = row

    data_json: Optional[dict[str, Any]] = None
    if data_json_str is not None:
        try:
            data_json = json.loads(data_json_str)
        except (json.JSONDecodeError, TypeError):
            data_json = data_json_str

    return {
        "id": node_id,
        "type": node_type,
        "name": name,
        "definition": definition,
        "tag": tag,
        "status": status,
        "data_json": data_json,
        "created_at": str(created_at) if created_at is not None else None,
        "updated_at": str(updated_at) if updated_at is not None else None,
    }
