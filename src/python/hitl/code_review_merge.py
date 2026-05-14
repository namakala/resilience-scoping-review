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
from inference.inference_status_crud import set_status_draft
from inference.inference_status_types import ENTITY_THEME, STAGE_THEME
from ontology import ConstraintError, validate_constraint
from persistence.state_updates import increment_user_action_count
from utils.logging import get_logger

from .user_action_log import log_user_action

logger = get_logger(__name__)

__all__ = ["handle_merge"]


def handle_merge(
    con: duckdb.DuckDBPyConnection,
    source_code: dict,
    target_id: int,
    db_path: Optional[Path] = None,
) -> None:
    """Merge *source_code* into the code identified by *target_id*.

    Steps:
        0. Pre-transaction validation (type check, constraint validator)
        1. Redirect ``contains`` edges from source to target
        2. Merge ``data_json`` (exemplar_ids, supporting_quotes)
        3. Clear source's data_json exemplar references; set ``merged_into``
        4. Create ``derived-from`` edge: source → target
        5. Invalidate downstream caches (themes → draft, interpretations → draft)
        6. Log user action and increment count (implicit COMMIT via ``save_state``)
        7. Rebuild the in-memory graph

    All database operations inside a single DuckDB transaction for atomicity,
    with NetworkX snapshot/restore for dual-representation consistency.

    .. note::
        ``increment_user_action_count`` calls ``save_state`` which performs
        an implicit ``con.commit()`` (see ``state_repository.save_state``).
        This means the transaction is committed at step 6.  Steps before
        step 6 roll back fully; after step 6 the commit is final.
    """
    source_id = source_code["id"]

    if source_id == target_id:
        logger.warning("Merge aborted: cannot merge code with itself")
        return

    # -- Pre-transaction validation -------------------------------------------

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
    entity = {
        "id": source_id,
        "type": source_type,
        "tag": source_code.get("tag", ""),
    }
    try:
        validate_constraint(entity, "merge")
    except ConstraintError:
        logger.exception("Merge constraint validation failed")
        raise

    # -- Prepare data for atomic transaction ----------------------------------

    src_dj = source_code.get("data_json") or {}
    tgt_dj = target_code.get("data_json") or {}

    src_eids = src_dj.get("exemplar_ids", [])
    src_quotes = src_dj.get("supporting_quotes", {})
    tgt_eids = tgt_dj.get("exemplar_ids", [])
    tgt_quotes = tgt_dj.get("supporting_quotes", {})

    merged_eids = list(dict.fromkeys(tgt_eids + src_eids))
    merged_quotes = {**tgt_quotes, **src_quotes}

    # -- Atomic transaction on the caller's connection ------------------------

    snapshot = copy.deepcopy(G)
    con.execute("BEGIN TRANSACTION")
    _active_tx_conn.set(con)
    _active_tx_db_path.set(db_path)
    committed = False  # becomes True once increment_user_action_count commits

    try:
        # 1. Redirect contains edges
        source_edges = con.execute(
            "SELECT target_id FROM edges "
            "WHERE source_id = ? AND edge_type = 'contains'",
            [source_id],
        ).fetchall()

        for (exemplar_id,) in source_edges:
            already_connected = con.execute(
                "SELECT 1 FROM edges "
                "WHERE source_id = ? AND target_id = ? AND edge_type = 'contains'",
                [target_id, exemplar_id],
            ).fetchone()

            if already_connected:
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

        # 2. Merge data_json into target
        tgt_dj["exemplar_ids"] = merged_eids
        tgt_dj["supporting_quotes"] = merged_quotes
        con.execute(
            "UPDATE nodes SET data_json = ?, "
            "updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            [json.dumps(tgt_dj, ensure_ascii=False), target_id],
        )

        # 3. Clear source's exemplar references and set merged_into
        src_dj.pop("exemplar_ids", None)
        src_dj.pop("supporting_quotes", None)
        src_dj["merged_into"] = target_id
        con.execute(
            "UPDATE nodes SET data_json = ?, status = 'merged', "
            "updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            [json.dumps(src_dj, ensure_ascii=False), source_id],
        )

        # 4. Create derived-from edge (uses active transaction connection)
        create_edge(
            source_id=source_id,
            target_id=target_id,
            edge_type="derived-from",
            db_path=db_path,
        )

        # 5. Downstream invalidation
        theme_ids = _invalidate_themes(con, source_id, target_id)
        _invalidate_interpretations(con, theme_ids)

        # 6. Log user action and increment count
        #    increment_user_action_count -> save_state -> con.commit()
        #    This implicitly commits the transaction.
        log_user_action(
            con,
            "merge",
            source_id,
            old_value={"status": source_code.get("status"), "merged_into": None},
            new_value={"status": "merged", "merged_into": target_id},
        )
        increment_user_action_count(con)

        # Transaction committed by save_state inside increment_user_action_count.
        committed = True
    except Exception:
        if not committed:
            # save_state never ran; we can safely roll back
            try:
                con.execute("ROLLBACK")
            except duckdb.TransactionException:
                logger.warning("Rollback failed; transaction may already be closed")
        raise
    finally:
        _active_tx_conn.set(None)
        _active_tx_db_path.set(None)
        if not committed:
            # Restore NetworkX graph from snapshot on failure
            from graph import singleton as _g_singleton

            _g_singleton._graph = snapshot
            clear_traversal_cache()

    # -- Post-commit: rebuild in-memory graph --------------------------------
    rebuild_graph(db_path)


def _invalidate_themes(con, source_id: int, target_id: int) -> list[int]:
    """Mark themes containing *source_id* or *target_id* as draft.

    Returns the list of affected theme IDs for cascade invalidation.
    """
    rows = con.execute(
        "SELECT DISTINCT source_id FROM edges "
        "WHERE target_id IN (?, ?) AND edge_type = 'composed-of'",
        [source_id, target_id],
    ).fetchall()
    theme_ids = [r[0] for r in rows]

    for theme_id in theme_ids:
        con.execute(
            "UPDATE nodes SET status = 'draft', updated_at = CURRENT_TIMESTAMP "
            "WHERE id = ?",
            [theme_id],
        )
        try:
            set_status_draft(con, str(theme_id), ENTITY_THEME, STAGE_THEME)
        except ValueError:
            logger.warning(
                "Could not set inference status to draft for theme",
                extra={"theme_id": theme_id},
            )

    if theme_ids:
        logger.info(
            "Themes invalidated to draft by merge",
            extra={"theme_ids": theme_ids},
        )

    return theme_ids


def _invalidate_interpretations(con, theme_ids: list[int]) -> None:
    """Mark interpretations spanning any of *theme_ids* as draft."""
    if not theme_ids:
        return

    placeholders = ",".join("?" for _ in theme_ids)
    rows = con.execute(
        f"SELECT DISTINCT source_id FROM edges "
        f"WHERE target_id IN ({placeholders}) AND edge_type = 'spans'",
        theme_ids,
    ).fetchall()
    interp_ids = [r[0] for r in rows]

    for interp_id in interp_ids:
        con.execute(
            "UPDATE nodes SET status = 'draft', updated_at = CURRENT_TIMESTAMP "
            "WHERE id = ?",
            [interp_id],
        )

    if interp_ids:
        logger.info(
            "Interpretations invalidated to draft by merge",
            extra={"interp_ids": interp_ids},
        )
