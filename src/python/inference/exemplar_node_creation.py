"""Create exemplar graph nodes if they do not exist.

Provides :func:`ensure_exemplar_nodes` which queries existing exemplar
nodes for a given tag and creates any that are missing in the graph.
Returns a mapping from exemplar ID (string) to graph node ID (int).

Usage:
    from inference.exemplar_node_creation import ensure_exemplar_nodes

    exemplar_map = ensure_exemplar_nodes(con, {"1", "2", "3"}, tag="T1")
    node_id = exemplar_map["1"]  # graph node ID for exemplar 1
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import duckdb
from graph import create_node, get_nodes_by_type_and_tag
from utils.logging import get_logger

logger = get_logger(__name__)

__all__ = ["ensure_exemplar_nodes"]


def ensure_exemplar_nodes(
    con: duckdb.DuckDBPyConnection,
    exemplar_ids: set[str],
    tag: str,
    db_path: Optional[Path] = None,
) -> dict[str, int]:
    """Create exemplar graph nodes for any missing *exemplar_ids*.

    Queries existing exemplar nodes for *tag* via their ``data_json``
    ``exemplar_id`` field, then creates new nodes for any IDs not yet
    present.  Exemplar nodes have ``type='exemplar'`` and
    ``status='immutable'``.

    Args:
        con: Active DuckDB connection (unused directly, passed for API
            consistency with other inference modules).
        exemplar_ids: Set of exemplar ID strings to ensure exist as
            graph nodes.
        tag: Ontology tag shared by all exemplar IDs.
        db_path: Optional DuckDB path for graph module.

    Returns:
        Dict mapping each exemplar ID string to its graph node ID.
        Includes both pre-existing and newly created nodes.
    """
    if not exemplar_ids:
        logger.warning("ensure_exemplar_nodes called with empty set; no-op")
        return {}

    existing_nodes = get_nodes_by_type_and_tag("exemplar", tag, db_path=db_path)

    result: dict[str, int] = {}
    for node in existing_nodes:
        dj = node.get("data_json") or {}
        if isinstance(dj, dict):
            eid = dj.get("exemplar_id")
            if eid is not None:
                result[str(eid)] = node["id"]

    missing = exemplar_ids - set(result.keys())
    if not missing:
        logger.debug(
            "All %d exemplar nodes already exist for tag '%s'",
            len(exemplar_ids),
            tag,
        )
        return result

    logger.info(
        "Creating %d exemplar nodes for tag '%s'",
        len(missing),
        tag,
    )

    for eid in sorted(missing):
        node_id = create_node(
            node_type="exemplar",
            name=f"exemplar_{eid}_{tag}",
            definition="",
            tag=tag,
            status="immutable",
            data_json={"exemplar_id": eid},
            db_path=db_path,
        )
        result[eid] = node_id

    logger.info(
        "Exemplar nodes ready: %d total for tag '%s'",
        len(result),
        tag,
    )
    return result
