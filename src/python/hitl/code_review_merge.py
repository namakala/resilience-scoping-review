"""Merge action handler for code review HITL CLI.

``handle_merge`` redirects ``contains`` edges from source to target,
merges ``data_json`` fields, creates a ``derived-from`` edge,
invalidates downstream caches, and persists all changes atomically
in a single DuckDB transaction with NetworkX snapshot/restore.
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
from persistence.state_updates import increment_user_action_count
from utils.logging import get_logger

from .merge_invalidation import invalidate_interpretations, invalidate_themes
from .user_action_log import log_user_action

logger = get_logger(__name__)

__all__ = ["handle_merge"]


def _redirect_contains_edges(con, source_id: int, target_id: int) -> None:
    """Redirect all ``contains`` edges from *source_id* to *target_id*.

    Deletes edges where the target already has a connection to avoid
    duplicate primary keys.  Updates edge source_id otherwise.
    """
    for (exemplar_id,) in con.execute(
        "SELECT target_id FROM edges " "WHERE source_id = ? AND edge_type = 'contains'",
        [source_id],
    ).fetchall():
        if con.execute(
            "SELECT 1 FROM edges "
            "WHERE source_id = ? AND target_id = ? AND edge_type = 'contains'",
            [target_id, exemplar_id],
        ).fetchone():
            con.execute(
                "DELETE FROM edges "
                "WHERE source_id = ? AND target_id = ? AND edge_type = 'contains'",
                [source_id, exemplar_id],
            )
        else:
            con.execute(
                "UPDATE edges SET source_id = ? "
                "WHERE source_id = ? AND target_id = ? AND edge_type = 'contains'",
                [target_id, source_id, exemplar_id],
            )


def _merge_data_json(
    con, source_id: int, target_id: int, src_dj: dict, tgt_dj: dict
) -> None:
    """Merge exemplar_ids and supporting_quotes into target; clear source.

    Sets ``merged_into`` on source's data_json and marks it ``merged``.
    """
    src_eids = src_dj.get("exemplar_ids", [])
    src_quotes = src_dj.get("supporting_quotes", {})
    tgt_eids = tgt_dj.get("exemplar_ids", [])
    tgt_quotes = tgt_dj.get("supporting_quotes", {})

    merged_eids = list(dict.fromkeys(tgt_eids + src_eids))
    merged_quotes = {**tgt_quotes, **src_quotes}

    tgt_dj["exemplar_ids"] = merged_eids
    tgt_dj["supporting_quotes"] = merged_quotes
    con.execute(
        "UPDATE nodes SET data_json = ?, "
        "updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        [json.dumps(tgt_dj, ensure_ascii=False), target_id],
    )

    src_dj.pop("exemplar_ids", None)
    src_dj.pop("supporting_quotes", None)
    src_dj["merged_into"] = target_id
    con.execute(
        "UPDATE nodes SET data_json = ?, status = 'merged', "
        "updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        [json.dumps(src_dj, ensure_ascii=False), source_id],
    )


def handle_merge(
    con: duckdb.DuckDBPyConnection,
    source_code: dict,
    target_id: int,
    db_path: Optional[Path] = None,
) -> None:
    """Merge *source_code* into the code identified by *target_id*.

    All database operations inside a single DuckDB transaction for atomicity,
    with NetworkX snapshot/restore for dual-representation consistency.

    .. note::
        ``increment_user_action_count`` calls ``save_state`` which performs
        an implicit ``con.commit()`` (see ``state_repository.save_state``).
        Steps before step 5 roll back fully; after step 5 the commit is final.
    """
    source_id = source_code["id"]
    if source_id == target_id:
        logger.warning("Merge aborted: cannot merge code with itself")
        return

    target_code = get_node(target_id, db_path=db_path)
    source_type = source_code.get("type", "code")
    target_type = target_code.get("type", "code")

    if source_type != target_type:
        raise ConstraintError(
            "CONSTRAINT_TYPE_MISMATCH",
            f"Cannot merge {source_type} '{source_code.get('name', source_id)}' "
            f"into {target_type} '{target_code.get('name', target_id)}'. "
            f"Both entities must be the same type.",
        )

    G = get_graph(db_path)
    try:
        validate_constraint(
            {"id": source_id, "type": source_type, "tag": source_code.get("tag", "")},
            "merge",
        )
    except ConstraintError:
        logger.exception("Merge constraint validation failed")
        raise

    src_dj = source_code.get("data_json") or {}
    tgt_dj = target_code.get("data_json") or {}
    snapshot = copy.deepcopy(G)

    con.execute("BEGIN TRANSACTION")
    _active_tx_conn.set(con)
    _active_tx_db_path.set(db_path)
    committed = False

    try:
        _redirect_contains_edges(con, source_id, target_id)
        _merge_data_json(con, source_id, target_id, src_dj, tgt_dj)
        create_edge(
            source_id=source_id,
            target_id=target_id,
            edge_type="derived-from",
            db_path=db_path,
        )
        theme_ids = invalidate_themes(con, source_id, target_id)
        invalidate_interpretations(con, theme_ids)

        log_user_action(
            con,
            "merge",
            source_id,
            old_value={"status": source_code.get("status"), "merged_into": None},
            new_value={"status": "merged", "merged_into": target_id},
        )
        increment_user_action_count(con)
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
