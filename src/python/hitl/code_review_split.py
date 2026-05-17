"""Split action handler for code review HITL.

``handle_split_code_regroup`` divides a code into N new codes by
letting the user iteratively select subsets of exemplars. Each
selected subset forms one group. All groups are sent through LLM
code inference to generate new names, definitions, and supporting
quotes.

The original code is marked ``superseded`` and ``derived-from`` edges
link it to all new nodes.
"""

import copy
import json
from pathlib import Path
from typing import Optional

import duckdb
from graph import clear_traversal_cache, rebuild_graph
from graph.singleton import get_graph
from graph.transactions import _active_tx_conn, _active_tx_db_path
from inference.code_inference import infer_codes
from inference.code_node_creation import create_code_nodes
from inference.inference_status_crud import set_status
from inference.inference_status_types import ENTITY_EXEMPLAR, PENDING, STAGE_CODE
from persistence.duckdb_connection import DEFAULT_DB_PATH
from persistence.state_updates import increment_user_action_count
from semantic.embedding_generation import generate_code_embeddings
from utils.logging import get_logger

from .invalidation import invalidate_interpretations, invalidate_themes
from .user_action_log import log_user_action

logger = get_logger(__name__)

__all__ = ["handle_split_code_regroup"]


def _build_merged_info(groups: list[list[int]]) -> dict:
    """Build the ``data_json`` merge metadata for the superseded code."""
    return {
        "merged_info": {
            "split_groups": groups,
        }
    }


def handle_split_code_regroup(
    con: duckdb.DuckDBPyConnection,
    code: dict,
    groups: list[list[int]],
    db_path: Optional[Path] = None,
) -> list[int]:
    """Split *code* into N new codes by regrouping exemplars.

    The original code is marked ``superseded``.  All exemplars across
    all groups are reset to ``pending`` in ``inference_status`` for the
    code stage, then ``infer_codes`` is called to re-infer names and
    definitions.

    Args:
        con: Active DuckDB connection.
        code: Original code dict (expects keys ``id``, ``name``,
            ``definition``, ``tag``, ``data_json``).
        groups: List of exemplar-ID groups. Each group becomes one new
            code. Must contain at least 2 groups.
        db_path: Optional DuckDB path for graph module.

    Returns:
        List of new code node IDs, one per group.

    Raises:
        ValueError: If fewer than 2 groups, or any group is empty.
    """
    source_id = code["id"]
    tag = code.get("tag", "")

    if len(groups) < 2:
        raise ValueError("Split requires at least 2 groups of exemplars.")
    for i, g in enumerate(groups):
        if not g:
            raise ValueError(f"Group {i+1} must have at least one exemplar.")

    db_path = db_path or DEFAULT_DB_PATH
    all_eids = [eid for g in groups for eid in g]

    # ── Step 1: Mark original as superseded ────────────────────────
    dj = code.get("data_json") or {}
    dj.update(_build_merged_info(groups))

    G = get_graph(db_path)
    snapshot = copy.deepcopy(G)

    con.execute("BEGIN TRANSACTION")
    _active_tx_conn.set(con)
    _active_tx_db_path.set(db_path)
    committed = False

    try:
        con.execute(
            "UPDATE nodes SET status = 'superseded', data_json = ?, "
            "updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            [json.dumps(dj, ensure_ascii=False), source_id],
        )

        # Delete contains edges from original code to its exemplars
        con.execute(
            "DELETE FROM edges WHERE source_id = ? AND edge_type = 'contains'",
            [source_id],
        )

        # Delete composed-of edges from themes pointing to this code
        con.execute(
            "DELETE FROM edges WHERE target_id = ? AND edge_type = 'composed-of'",
            [source_id],
        )

        # Reset inference_status for split exemplars to pending
        for eid in all_eids:
            set_status(
                con,
                entity_id=str(eid),
                entity_type=ENTITY_EXEMPLAR,
                stage=STAGE_CODE,
                status=PENDING,
            )

        committed = True
        con.execute("COMMIT")

    except Exception:
        if not committed:
            try:
                con.execute("ROLLBACK")
            except duckdb.TransactionException:
                logger.warning(
                    "Rollback failed during code split; "
                    "transaction may already be closed"
                )
        raise

    finally:
        _active_tx_conn.set(None)
        _active_tx_db_path.set(None)
        if not committed:
            from graph import singleton as _g_singleton

            _g_singleton._graph = snapshot
            clear_traversal_cache()

    # ── Step 2: Re-infer codes via LLM ─────────────────────────────
    try:
        codes = infer_codes(con, tag=tag)
        if not codes:
            logger.warning(
                "Code re-inference produced no results for tag '%s' (code %d split)",
                tag,
                source_id,
            )
            rebuild_graph(db_path)
            return []

        node_ids = create_code_nodes(con, codes, db_path=db_path)
        generate_code_embeddings(con)
    except Exception as exc:
        logger.error(
            "Code re-inference failed for split (code %d): %s",
            source_id,
            exc,
        )
        rebuild_graph(db_path)
        raise

    # ── Step 3: Invalidate downstream caches ──────────────────────
    try:
        affected_theme_ids = invalidate_themes(con, source_id, source_id)
        if affected_theme_ids:
            invalidate_interpretations(con, affected_theme_ids)
    except Exception as exc:
        logger.warning(
            "Downstream invalidation failed after code split: %s",
            exc,
        )

    # ── Step 4: Finalize ──────────────────────────────────────────
    rebuild_graph(db_path)

    log_user_action(
        con,
        "split",
        source_id,
        old_value={
            "status": code.get("status", "draft"),
            "exemplar_ids": all_eids,
        },
        new_value={
            "status": "superseded",
            "split_into": node_ids,
        },
    )
    increment_user_action_count(con)

    logger.info(
        "Code %d split into %d new codes (node_ids: %s)",
        source_id,
        len(node_ids),
        node_ids,
    )

    return node_ids
