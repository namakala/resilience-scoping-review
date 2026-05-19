"""Merge action handler for interpretation review HITL CLI.

``handle_merge_interpretations`` redirects ``spans`` edges from source to
target, merges ``theme_ids``, ``tag_spans``, and ``key_insights`` in
``data_json``, creates a ``derived-from`` edge, invalidates caches, and
persists all changes atomically in a single DuckDB transaction with
NetworkX snapshot/restore.
"""

import copy
import json
from pathlib import Path
from typing import Optional

import duckdb
from graph import clear_traversal_cache, create_edge, rebuild_graph
from graph.queries import get_node, is_theme_in_any_interpretation
from graph.singleton import get_graph
from graph.transactions import _active_tx_conn, _active_tx_db_path
from ontology import ConstraintError, validate_constraint
from persistence.embedding_cache import invalidate_entity
from persistence.state_updates import increment_user_action_count, update_dirty_flag
from utils.logging import get_logger

from .user_action_log import log_user_action

logger = get_logger(__name__)

__all__ = ["handle_merge_interpretations"]


def _redirect_spans_edges(
    con,
    source_id: int,
    target_id: int,
    db_path: Optional[Path] = None,
) -> None:
    """Redirect all ``spans`` edges from *source_id* to *target_id*.

    Deletes edges where the target already has a connection to avoid
    duplicate primary keys.  Updates edge source_id otherwise.

    Skips themes that already belong to a third (non-merged)
    interpretation (enforces one-theme-per-interpretation).
    """
    for (theme_id,) in con.execute(
        "SELECT target_id FROM edges " "WHERE source_id = ? AND edge_type = 'spans'",
        [source_id],
    ).fetchall():
        # Enforce: one theme belongs to at most one interpretation
        already_in, existing_iid, existing_iname = is_theme_in_any_interpretation(
            theme_id, db_path=db_path
        )
        if already_in and existing_iid not in (source_id, target_id):
            logger.warning(
                "Theme %s already spanned by interpretation '%s' (id=%s) — "
                "cannot redirect to interpretation (id=%s). Deleting edge instead.",
                theme_id,
                existing_iname,
                existing_iid,
                target_id,
            )
            con.execute(
                "DELETE FROM edges "
                "WHERE source_id = ? AND target_id = ? AND edge_type = 'spans'",
                [source_id, theme_id],
            )
            continue

        if con.execute(
            "SELECT 1 FROM edges "
            "WHERE source_id = ? AND target_id = ? AND edge_type = 'spans'",
            [target_id, theme_id],
        ).fetchone():
            con.execute(
                "DELETE FROM edges "
                "WHERE source_id = ? AND target_id = ? AND edge_type = 'spans'",
                [source_id, theme_id],
            )
        else:
            con.execute(
                "UPDATE edges SET source_id = ? "
                "WHERE source_id = ? AND target_id = ? AND edge_type = 'spans'",
                [target_id, source_id, theme_id],
            )


def _merge_interpretation_data_json(
    con,
    source_id: int,
    target_id: int,
    src_dj: dict,
    tgt_dj: dict,
) -> None:
    """Merge ``theme_ids``, ``tag_spans``, and ``key_insights`` into target.

    Sets ``merged_into`` on source's data_json and marks it ``merged``.
    """
    src_theme_ids = src_dj.get("theme_ids", [])
    tgt_theme_ids = tgt_dj.get("theme_ids", [])
    merged_theme_ids = list(dict.fromkeys(tgt_theme_ids + src_theme_ids))

    src_tag_spans = src_dj.get("tag_spans", [])
    tgt_tag_spans = tgt_dj.get("tag_spans", [])
    merged_tag_spans = sorted(set(tgt_tag_spans + src_tag_spans))

    src_insights = src_dj.get("key_insights", [])
    tgt_insights = tgt_dj.get("key_insights", [])
    merged_insights = list(dict.fromkeys(tgt_insights + src_insights))

    tgt_dj["theme_ids"] = merged_theme_ids
    tgt_dj["tag_spans"] = merged_tag_spans
    tgt_dj["key_insights"] = merged_insights
    con.execute(
        "UPDATE nodes SET data_json = ?, "
        "updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        [json.dumps(tgt_dj, ensure_ascii=False), target_id],
    )

    src_dj.pop("theme_ids", None)
    src_dj.pop("tag_spans", None)
    src_dj.pop("key_insights", None)
    src_dj["merged_into"] = target_id
    con.execute(
        "UPDATE nodes SET data_json = ?, status = 'merged', "
        "updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        [json.dumps(src_dj, ensure_ascii=False), source_id],
    )


def handle_merge_interpretations(
    con: duckdb.DuckDBPyConnection,
    source_interp: dict,
    target_id: int,
    db_path: Optional[Path] = None,
) -> None:
    """Merge *source_interp* into the interpretation identified by *target_id*.

    All database operations inside a single DuckDB transaction for
    atomicity, with NetworkX snapshot/restore for dual-representation
    consistency.
    """
    source_id = source_interp["id"]
    if source_id == target_id:
        logger.warning("Merge aborted: cannot merge interpretation with itself")
        return

    target_interp = get_node(target_id, db_path=db_path)
    source_type = source_interp.get("type", "interpretation")
    target_type = target_interp.get("type", "interpretation")

    if source_type != target_type:
        raise ConstraintError(
            "CONSTRAINT_TYPE_MISMATCH",
            f"Cannot merge {source_type} '{source_interp.get('name', source_id)}' "
            f"into {target_type} '{target_interp.get('name', target_id)}'. "
            f"Both entities must be the same type.",
        )

    G = get_graph(db_path)
    try:
        validate_constraint(
            {
                "id": source_id,
                "type": source_type,
                "tag": source_interp.get("tag", ""),
                "target_status": target_interp.get("status"),
            },
            "merge",
        )
    except ConstraintError:
        logger.exception("Merge constraint validation failed")
        raise

    src_dj = source_interp.get("data_json") or {}
    tgt_dj = target_interp.get("data_json") or {}
    snapshot = copy.deepcopy(G)

    con.execute("BEGIN TRANSACTION")
    _active_tx_conn.set(con)
    _active_tx_db_path.set(db_path)
    committed = False

    try:
        _redirect_spans_edges(con, source_id, target_id, db_path=db_path)
        _merge_interpretation_data_json(con, source_id, target_id, src_dj, tgt_dj)
        create_edge(
            source_id=source_id,
            target_id=target_id,
            edge_type="derived-from",
            db_path=db_path,
        )

        # Invalidate embeddings for both source and target
        invalidate_entity(con, str(source_id), "interpretation")
        invalidate_entity(con, str(target_id), "interpretation")

        con.execute("COMMIT")

        # State management (outside transaction — save_state calls con.commit())
        log_user_action(
            con,
            "merge",
            source_id,
            old_value={"status": source_interp.get("status"), "merged_into": None},
            new_value={"status": "merged", "merged_into": target_id},
        )
        increment_user_action_count(con)

        # Set dirty flags for all tags in the merged tag_spans
        for tag in tgt_dj.get("tag_spans", []):
            if tag:
                update_dirty_flag(con, tag)

        committed = True
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
