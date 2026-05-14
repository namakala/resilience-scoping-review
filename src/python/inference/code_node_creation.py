"""Convert CodeInference results into graph code nodes with edges.

For each :class:`CodeInference` item creates:

- A ``code`` graph node (type='code', status='draft')
- A ``contains`` edge from the code node to the exemplar node
- A ``derived-from`` edge from any pre-existing code for the same
  exemplar (versioning chain)

All graph writes within a single
:class:`~graph.transactions.graph_transaction` for atomicity.

Usage:
    from inference.code_node_creation import create_code_nodes

    codes = infer_codes(con, tag="T1")
    node_ids = create_code_nodes(con, codes)
"""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any, Optional

import duckdb
from graph import create_edge, create_node, get_nodes_by_type_and_tag, graph_transaction
from utils.logging import get_logger

from .batching import group_items_by_tag
from .exemplar_node_creation import ensure_exemplar_nodes
from .inference_status_crud import set_status
from .inference_status_types import ENTITY_CODE, GENERATED, STAGE_CODE
from .parsing import CodeInference

logger = get_logger(__name__)

__all__ = ["create_code_nodes"]


def _collect_exemplar_ids(codes: list[CodeInference]) -> set[str]:
    """Collect unique exemplar ID strings from a list of CodeInference."""
    return {c.exemplar_id for c in codes}


def _build_existing_code_map(
    tag: str,
    db_path: Optional[Path] = None,
) -> dict[str, list[int]]:
    """Build ``{exemplar_id: [existing_code_node_id, ...]}`` for *tag*.

    Reads ``data_json['exemplar_id']`` from each existing code node to
    determine which exemplar it is linked to.
    """
    nodes = get_nodes_by_type_and_tag("code", tag, db_path=db_path)
    code_map: dict[str, list[int]] = defaultdict(list)
    for n in nodes:
        dj = n.get("data_json") or {}
        if isinstance(dj, dict):
            eids = dj.get("exemplar_ids", [])
            if eids:
                code_map[str(eids[0])].append(n["id"])
    return dict(code_map)


def _build_data_json(code: CodeInference) -> dict[str, Any]:
    """Build the ``data_json`` payload for a code node."""
    return {
        "exemplar_ids": [code.exemplar_id],
        "supporting_quotes": {code.exemplar_id: code.supporting_quote},
        "related_existing_codes": code.related_existing_codes,
    }


# ── Public API ─────────────────────────────────────────────────────────────


def create_code_nodes(
    con: duckdb.DuckDBPyConnection,
    codes: list[CodeInference],
    db_path: Optional[Path] = None,
) -> list[int]:
    """Convert *codes* into graph nodes with ``contains`` edges.

    For each :class:`CodeInference` item:

    1. Creates a ``code`` graph node (type='code', status='draft')
    2. Creates a ``contains`` edge from the code node → exemplar node
    3. If a pre-existing code node is linked to the same exemplar,
       creates a ``derived-from`` edge pre-existing → new code

    Exemplar graph nodes are automatically created if missing.

    All graph mutations are wrapped in a single
    :class:`~graph.transactions.graph_transaction` for atomicity.
    After the transaction succeeds, each code entity's
    ``inference_status`` is set to ``generated``.

    Args:
        con: Active DuckDB connection (used for inference_status
            updates after graph transaction).
        codes: List of :class:`CodeInference` items.  Each item must
            have its ``tag`` field populated (set by
            :func:`~inference.code_inference.infer_codes`).
        db_path: Optional DuckDB path for graph module.

    Returns:
        List of created code node IDs in the same order as *codes*.

    Raises:
        ValueError: If a ``CodeInference`` has an empty ``tag``.
    """
    if not codes:
        logger.warning("create_code_nodes called with empty list; no-op")
        return []

    # Group by tag so we process one tag's exemplar nodes at a time.
    by_tag = group_items_by_tag(codes)
    all_node_ids: list[int] = []

    for tag, tag_codes in by_tag.items():
        if not tag:
            raise ValueError("CodeInference items must have a non-empty 'tag' field")
        node_ids = _create_code_nodes_for_tag(con, tag_codes, tag, db_path=db_path)
        all_node_ids.extend(node_ids)

    return all_node_ids


def _make_unique_name(
    name: str,
    used_names: set[str],
) -> str:
    """Resolve name collision by appending ``_1``, ``_2``, etc."""
    if name not in used_names:
        return name
    counter = 1
    while f"{name}_{counter}" in used_names:
        counter += 1
    logger.warning(
        "Duplicate code name '%s' resolved to '%s_%d'",
        name,
        name,
        counter,
    )
    return f"{name}_{counter}"


def _load_existing_code_names(
    tag: str,
    db_path: Optional[Path] = None,
) -> set[str]:
    """Fetch all existing code node names for *tag*."""
    nodes = get_nodes_by_type_and_tag("code", tag, db_path=db_path)
    return {n["name"] for n in nodes}


def _create_code_nodes_for_tag(
    con: duckdb.DuckDBPyConnection,
    codes: list[CodeInference],
    tag: str,
    db_path: Optional[Path] = None,
) -> list[int]:
    """Create code nodes for a single tag.

    1. Ensure exemplar nodes exist (prerequisite)
    2. Find existing code names and existing code->exemplar map
    3. Inside a ``graph_transaction``: create code nodes + edges
    4. Update inference_status for each new code entity
    """
    exemplar_ids = _collect_exemplar_ids(codes)

    # Step 1: ensure exemplar graph nodes exist
    exemplar_node_map = ensure_exemplar_nodes(con, exemplar_ids, tag, db_path=db_path)

    # Step 2a: find existing code nodes for derived-from chaining
    existing_code_map = _build_existing_code_map(tag, db_path=db_path)

    # Step 2b: load existing names to avoid (type, name) collisions
    existing_names = _load_existing_code_names(tag, db_path=db_path)
    used_names: set[str] = set(existing_names)

    # Step 3: create code nodes + edges inside a transaction
    node_ids: list[int] = []
    with graph_transaction(db_path=db_path):
        for c in codes:
            unique_name = _make_unique_name(c.code_name, used_names)
            used_names.add(unique_name)

            data_json = _build_data_json(c)
            node_id = create_node(
                node_type="code",
                name=unique_name,
                definition=c.definition,
                tag=tag,
                status="draft",
                data_json=data_json,
                db_path=db_path,
            )
            node_ids.append(node_id)

            # contains edge: code node → exemplar node
            target_nid = exemplar_node_map[c.exemplar_id]
            create_edge(
                source_id=node_id,
                target_id=target_nid,
                edge_type="contains",
                db_path=db_path,
            )

            # derived-from edge: latest existing code → new code
            # (linear version chain, not fan-out from all prior)
            prev_ids = existing_code_map.get(c.exemplar_id, [])
            if prev_ids:
                latest_prev = max(prev_ids)
                create_edge(
                    source_id=latest_prev,
                    target_id=node_id,
                    edge_type="derived-from",
                    db_path=db_path,
                )

    # Step 4: update inference_status for code entities
    for node_id in node_ids:
        set_status(
            con,
            entity_id=str(node_id),
            entity_type=ENTITY_CODE,
            stage=STAGE_CODE,
            status=GENERATED,
        )

    logger.info(
        "Created %d code nodes for tag '%s'",
        len(node_ids),
        tag,
    )
    return node_ids
