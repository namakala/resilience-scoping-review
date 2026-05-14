"""Merge action handler for theme review HITL CLI.

``handle_merge_themes`` redirects ``composed-of`` edges from source to
target, combines code sets, creates a ``derived-from`` edge,
invalidates downstream interpretations, and persists all changes
atomically in a single DuckDB transaction with NetworkX
snapshot/restore.
"""

import copy
import json
from pathlib import Path
from typing import Optional

import duckdb
from graph import clear_traversal_cache, create_edge, rebuild_graph
from graph.queries import get_node
from graph.singleton import get_graph
from graph.transactions import _active_tx_conn, _active_tx_db_path
from ontology import ConstraintError, validate_constraint
from persistence.embedding_cache import invalidate_entity
from persistence.state_updates import increment_user_action_count, update_dirty_flag
from utils.logging import get_logger

from .merge_invalidation import invalidate_interpretations
from .user_action_log import log_user_action

logger = get_logger(__name__)

__all__ = ["handle_merge_themes"]


def _redirect_composed_of_edges(con, source_id: int, target_id: int) -> None:
    """Redirect all ``composed-of`` edges from *source_id* to *target_id*.

    Deletes edges where the target already has a connection to avoid
    duplicate primary keys.  Updates edge source_id otherwise.
    """
    for (code_id,) in con.execute(
        "SELECT target_id FROM edges "
        "WHERE source_id = ? AND edge_type = 'composed-of'",
        [source_id],
    ).fetchall():
        if con.execute(
            "SELECT 1 FROM edges "
            "WHERE source_id = ? AND target_id = ? AND edge_type = 'composed-of'",
            [target_id, code_id],
        ).fetchone():
            con.execute(
                "DELETE FROM edges "
                "WHERE source_id = ? AND target_id = ? AND edge_type = 'composed-of'",
                [source_id, code_id],
            )
        else:
            con.execute(
                "UPDATE edges SET source_id = ? "
                "WHERE source_id = ? AND target_id = ? AND edge_type = 'composed-of'",
                [target_id, source_id, code_id],
            )


def _merge_theme_data_json(
    con,
    source_id: int,
    target_id: int,
    src_dj: dict,
    tgt_dj: dict,
) -> None:
    """Merge ``code_ids`` into target; clear source.

    Sets ``merged_into`` on source's data_json and marks it ``merged``.
    """
    src_ids = src_dj.get("code_ids", [])
    tgt_ids = tgt_dj.get("code_ids", [])

    merged_ids = list(dict.fromkeys(tgt_ids + src_ids))

    tgt_dj["code_ids"] = merged_ids
    con.execute(
        "UPDATE nodes SET data_json = ?, "
        "updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        [json.dumps(tgt_dj, ensure_ascii=False), target_id],
    )

    src_dj.pop("code_ids", None)
    src_dj["merged_into"] = target_id
    con.execute(
        "UPDATE nodes SET data_json = ?, status = 'merged', "
        "updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        [json.dumps(src_dj, ensure_ascii=False), source_id],
    )


def handle_merge_themes(
    con: duckdb.DuckDBPyConnection,
    source_theme: dict,
    target_id: int,
    db_path: Optional[Path] = None,
) -> None:
    """Merge *source_theme* into the theme identified by *target_id*.

    All database operations inside a single DuckDB transaction for
    atomicity, with NetworkX snapshot/restore for dual-representation
    consistency.
    """
    source_id = source_theme["id"]
    if source_id == target_id:
        logger.warning("Merge aborted: cannot merge theme with itself")
        return

    target_theme = get_node(target_id, db_path=db_path)
    source_type = source_theme.get("type", "theme")
    target_type = target_theme.get("type", "theme")

    if source_type != target_type:
        raise ConstraintError(
            "CONSTRAINT_TYPE_MISMATCH",
            f"Cannot merge {source_type} '{source_theme.get('name', source_id)}' "
            f"into {target_type} '{target_theme.get('name', target_id)}'. "
            f"Both entities must be the same type.",
        )

    G = get_graph(db_path)
    try:
        validate_constraint(
            {
                "id": source_id,
                "type": source_type,
                "tag": source_theme.get("tag", ""),
            },
            "merge",
        )
    except ConstraintError:
        logger.exception("Merge constraint validation failed")
        raise

    src_dj = source_theme.get("data_json") or {}
    tgt_dj = target_theme.get("data_json") or {}
    snapshot = copy.deepcopy(G)

    con.execute("BEGIN TRANSACTION")
    _active_tx_conn.set(con)
    _active_tx_db_path.set(db_path)
    committed = False

    try:
        _redirect_composed_of_edges(con, source_id, target_id)
        _merge_theme_data_json(con, source_id, target_id, src_dj, tgt_dj)
        create_edge(
            source_id=source_id,
            target_id=target_id,
            edge_type="derived-from",
            db_path=db_path,
        )

        # Invalidate downstream interpretations
        invalidate_interpretations(con, [source_id, target_id])

        # Invalidate embeddings for both source and target
        invalidate_entity(con, str(source_id), "theme")
        invalidate_entity(con, str(target_id), "theme")

        log_user_action(
            con,
            "merge",
            source_id,
            old_value={"status": source_theme.get("status"), "merged_into": None},
            new_value={"status": "merged", "merged_into": target_id},
        )
        increment_user_action_count(con)
        committed = True

        # Set dirty flag for the tag branch (after transaction is committed)
        tag = source_theme.get("tag", "")
        if tag:
            update_dirty_flag(con, tag)
    except Exception:
        if not committed:
            try:
                con.execute("ROLLBACK")
            except duckdb.TransactionException:
                logger.warning("Rollback failed; transaction may already be closed")
        raise
    finally:
        _active_tx_conn.set(None)
        _active_tx_db_path.set(None)
        if not committed:
            from graph import singleton as _g_singleton

            _g_singleton._graph = snapshot
            clear_traversal_cache()

    rebuild_graph(db_path)
