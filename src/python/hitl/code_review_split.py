"""Split action handler for code review HITL.

``handle_split_code_regroup`` divides a code into two by letting the
user select a subset of exemplars for the first new code; the remaining
exemplars form the second.  Both groups are sent through LLM code
inference to generate new names, definitions, and supporting quotes.

The original code is marked ``superseded`` and ``derived-from`` edges
link it to the two new nodes.
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


def _build_merged_info(
    first_ids: list[int],
    second_ids: list[int],
) -> dict:
    """Build the ``data_json`` merge metadata for the superseded code."""
    return {
        "merged_info": {
            "split_first_exemplar_ids": first_ids,
            "split_second_exemplar_ids": second_ids,
        }
    }


def handle_split_code_regroup(
    con: duckdb.DuckDBPyConnection,
    code: dict,
    first_exemplar_ids: list[int],
    second_exemplar_ids: list[int],
    db_path: Optional[Path] = None,
) -> tuple[int, int]:
    """Split *code* into two new codes by regrouping exemplars.

    The original code is marked ``superseded``.  The exemplars in both
    groups are reset to ``pending`` in ``inference_status`` for the code
    stage, then ``infer_codes`` is called to re-infer names/definitions
    for both groups.

    Args:
        con: Active DuckDB connection.
        code: Original code dict (expects keys ``id``, ``name``,
            ``definition``, ``tag``, ``data_json``).
        first_exemplar_ids: Exemplar IDs for the first new code.
        second_exemplar_ids: Exemplar IDs for the second new code.
        db_path: Optional DuckDB path for graph module.

    Returns:
        Tuple of ``(first_new_id, second_new_id)``.

    Raises:
        ValueError: If either exemplar list is empty.
    """
    source_id = code["id"]
    tag = code.get("tag", "")

    if not first_exemplar_ids or not second_exemplar_ids:
        raise ValueError("Both split codes must have at least one exemplar.")

    db_path = db_path or DEFAULT_DB_PATH
    all_eids = first_exemplar_ids + second_exemplar_ids

    # ── Step 1: Mark original as superseded ────────────────────────
    dj = code.get("data_json") or {}
    dj.update(_build_merged_info(first_exemplar_ids, second_exemplar_ids))

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
                "Code re-inference produced no results for tag '%s' " "(code %d split)",
                tag,
                source_id,
            )
            rebuild_graph(db_path)
            return -1, -1

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

    # Return first two created node IDs
    if len(node_ids) >= 2:
        return node_ids[0], node_ids[1]
    return node_ids[0], -1
