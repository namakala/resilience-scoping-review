"""Convert CodeInference results into graph code nodes with edges.

Groups :class:`CodeInference` items by ``code_name`` to create shared
abstract code nodes. Multiple exemplars mapping to the same abstract
code share a single graph node.

For each unique ``code_name`` in a tag:

- Creates (or merges into) a ``code`` graph node (type='code', status='draft')
- Creates ``contains`` edges from the code node to each exemplar node

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
from graph import (
    create_edge,
    create_node,
    get_graph,
    get_node,
    get_nodes_by_type_and_tag,
    graph_transaction,
)
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


def _build_data_json(
    exemplar_ids: list[str],
    supporting_quotes: dict[str, str],
    related_existing_codes: list[str],
) -> dict[str, Any]:
    """Build the ``data_json`` payload for a code node."""
    return {
        "exemplar_ids": exemplar_ids,
        "supporting_quotes": supporting_quotes,
        "related_existing_codes": related_existing_codes,
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


def _load_all_code_names(
    db_path: Optional[Path] = None,
) -> set[str]:
    """Fetch ALL existing code node names across all tags.

    Used for cross-tag collision detection after tag-scoped dedup.
    """
    nodes = get_nodes_by_type_and_tag("code", None, db_path=db_path)
    return {n["name"] for n in nodes}


def _find_draft_code_by_name(
    tag: str,
    name: str,
    db_path: Optional[Path] = None,
) -> int | None:
    """Find an existing draft code node by tag and exact name.

    Returns the node ID if found, None otherwise.  Only matches draft
    status codes to allow merging during current inference run.
    """
    nodes = get_nodes_by_type_and_tag("code", tag, db_path=db_path)
    for n in nodes:
        if n.get("name") == name and n.get("status") == "draft":
            return int(n["id"])
    return None


def _create_code_nodes_for_tag(
    con: duckdb.DuckDBPyConnection,
    codes: list[CodeInference],
    tag: str,
    db_path: Optional[Path] = None,
) -> list[int]:
    """Create code nodes for a single tag with shared abstract codes.

    1. Ensure exemplar nodes exist (prerequisite)
    2. Find existing code->exemplar map for derived-from chaining
    3. Group CodeInference items by code_name for shared abstract codes
    4. Inside a ``graph_transaction``: create/update code nodes + edges
    5. Update inference_status for each new code entity
    """
    exemplar_ids = _collect_exemplar_ids(codes)

    # Step 1: ensure exemplar graph nodes exist
    exemplar_node_map = ensure_exemplar_nodes(con, exemplar_ids, tag, db_path=db_path)

    # Step 2: load existing names to detect external collisions
    existing_names = _load_existing_code_names(tag, db_path=db_path)
    # Also load ALL code names globally for cross-tag collision safety net
    all_code_names = _load_all_code_names(db_path=db_path)

    # Step 4: group codes by code_name for shared abstract codes
    by_name: dict[str, list[CodeInference]] = defaultdict(list)
    for c in codes:
        by_name[c.code_name].append(c)

    # Step 5: create code nodes + edges inside a transaction
    node_ids: list[int] = []
    with graph_transaction(db_path=db_path):
        for code_name, group in by_name.items():
            # Check if a draft code with this name already exists (merge case)
            draft_id = _find_draft_code_by_name(tag, code_name, db_path=db_path)

            # Collect all exemplar data from the group
            all_eids = [c.exemplar_id for c in group]
            all_quotes = {c.exemplar_id: c.supporting_quote for c in group}
            all_related = []
            for c in group:
                all_related.extend(c.related_existing_codes)
            definition = group[0].definition

            if draft_id is not None:
                # Merge: append exemplar data into existing draft code node
                existing = get_node(draft_id, db_path=db_path)
                old_dj = existing.get("data_json") or {}
                old_eids = old_dj.get("exemplar_ids", [])
                old_quotes = old_dj.get("supporting_quotes", {})
                old_related = old_dj.get("related_existing_codes", [])

                merged_eids = list(set(old_eids + all_eids))
                merged_quotes = {**old_quotes, **all_quotes}
                merged_related = list(set(old_related + all_related))
                merged_dj = _build_data_json(merged_eids, merged_quotes, merged_related)

                # Update DuckDB inside the active transaction
                import json as _json

                from graph.transactions import get_active_connection

                tx_con = get_active_connection()
                if tx_con is None:
                    raise RuntimeError("Merge requires an active graph_transaction")
                tx_con.execute(
                    "UPDATE nodes SET data_json = ? WHERE id = ?",
                    [_json.dumps(merged_dj, ensure_ascii=False), draft_id],
                )

                # Update in-memory graph
                G = get_graph(db_path)
                attrs = dict(G.nodes[draft_id])
                attrs["data_json"] = merged_dj
                G.add_node(draft_id, **attrs)

                node_ids.append(draft_id)

                # Create contains edges for new exemplars
                for eid in all_eids:
                    if eid not in old_eids:
                        create_edge(
                            source_id=draft_id,
                            target_id=exemplar_node_map[eid],
                            edge_type="contains",
                            db_path=db_path,
                        )
            else:
                # Create unique name if collision with existing (non-draft) codes
                unique_name = _make_unique_name(code_name, existing_names)

                # Cross-tag collision safety net: check against ALL code names
                if unique_name in all_code_names:
                    qualified = f"{unique_name} [{tag}]"
                    logger.warning(
                        "Cross-tag code name collision '%s' resolved to '%s'",
                        unique_name,
                        qualified,
                    )
                    unique_name = _make_unique_name(qualified, all_code_names)

                data_json = _build_data_json(all_eids, all_quotes, all_related)
                node_id = create_node(
                    node_type="code",
                    name=unique_name,
                    definition=definition,
                    tag=tag,
                    status="draft",
                    data_json=data_json,
                    db_path=db_path,
                )
                node_ids.append(node_id)

                # Create contains edges for all exemplars
                for c in group:
                    target_nid = exemplar_node_map[c.exemplar_id]
                    create_edge(
                        source_id=node_id,
                        target_id=target_nid,
                        edge_type="contains",
                        db_path=db_path,
                    )

    # Step 6: update inference_status for code entities
    for node_id in node_ids:
        set_status(
            con,
            entity_id=str(node_id),
            entity_type=ENTITY_CODE,
            stage=STAGE_CODE,
            status=GENERATED,
        )

    logger.info(
        "Created %d code nodes (shared abstract codes) for tag '%s'",
        len(node_ids),
        tag,
    )
    return node_ids
