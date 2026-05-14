"""Simple action handlers for interpretation review HITL CLI.

Provides ``handle_approve_interpretation``, ``handle_edit_interpretation``,
``handle_reject_interpretation``, and ``handle_defer_interpretation`` plus
private helpers for node updates.
"""

from pathlib import Path
from typing import Any, Optional

import duckdb
from graph import sync_node
from inference.inference_status_crud import set_status, set_status_draft
from inference.inference_status_types import (
    APPROVED,
    ENTITY_INTERPRETATION,
    REJECTED,
    STAGE_INTERPRETATION,
)
from persistence.state_updates import increment_user_action_count
from utils.logging import get_logger

from .edits import invalidate_interpretation_embedding
from .user_action_log import log_user_action

logger = get_logger(__name__)

__all__ = [
    "handle_approve_interpretation",
    "handle_edit_interpretation",
    "handle_reject_interpretation",
    "handle_defer_interpretation",
]


# ── Node update helpers ────────────────────────────────────────────


def _update_interpretation_status(
    con: duckdb.DuckDBPyConnection,
    node_id: int,
    new_status: str,
    db_path: Optional[Path] = None,
) -> None:
    """Update node status in DuckDB and sync the in-memory graph."""
    con.execute(
        "UPDATE nodes SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        [new_status, node_id],
    )
    sync_node(node_id, db_path)


def _update_interpretation_narrative(
    con: duckdb.DuckDBPyConnection,
    node_id: int,
    new_narrative: str,
    db_path: Optional[Path] = None,
) -> None:
    """Update node narrative (stored in ``definition``) and reset status to draft.

    Preserves ``tag`` and ``data_json.tag_spans`` unchanged.
    """
    con.execute(
        "UPDATE nodes SET definition = ?, status = 'draft', "
        "updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        [new_narrative, node_id],
    )
    sync_node(node_id, db_path)


# ── Action handlers ────────────────────────────────────────────────


def handle_approve_interpretation(
    con: duckdb.DuckDBPyConnection,
    interp: dict[str, Any],
    db_path: Optional[Path] = None,
) -> None:
    """Approve an interpretation: validate constraints, set status and inference status.

    Checks ADR-013 constraints via ``validate_constraint`` before
    approving.  If constraints fail, prints error and returns without
    modifying state.
    """
    node_id = interp["id"]
    dj = interp.get("data_json") or {}
    tag_spans = set(dj.get("tag_spans", []))

    try:
        from ontology import ConstraintError, validate_constraint

        validate_constraint(
            {
                "id": node_id,
                "type": "interpretation",
                "tag_spans": tag_spans,
            },
            "approve",
        )
    except ConstraintError as exc:
        from .interpretation_review_display import console

        console.print(f"[red]Constraint violation: {exc}[/red]")
        logger.warning(
            "Interpretation approve rejected by constraint",
            extra={"error": str(exc), "constraint_type": exc.code},
        )
        return

    _update_interpretation_status(con, node_id, "approved", db_path=db_path)
    set_status(
        con,
        entity_id=str(node_id),
        entity_type=ENTITY_INTERPRETATION,
        stage=STAGE_INTERPRETATION,
        status=APPROVED,
    )
    log_user_action(con, "approve", node_id)
    increment_user_action_count(con)


def handle_edit_interpretation(
    con: duckdb.DuckDBPyConnection,
    interp: dict[str, Any],
    db_path: Optional[Path] = None,
    new_narrative: str = "",
) -> None:
    """Edit an interpretation: update narrative, reset to draft, invalidate cache.

    Preserves ``tag`` and ``tag_spans`` — scope cannot be changed via edit.
    """
    node_id = interp["id"]
    old_narrative = interp.get("narrative", "")

    if not new_narrative.strip():
        logger.warning("Edit aborted: empty narrative")
        return

    if new_narrative == old_narrative:
        logger.info("Edit aborted: narrative unchanged")
        return

    _update_interpretation_narrative(con, node_id, new_narrative, db_path=db_path)
    set_status_draft(
        con,
        entity_id=str(node_id),
        entity_type=ENTITY_INTERPRETATION,
        stage=STAGE_INTERPRETATION,
    )

    # Invalidate embedding for the interpretation
    tag_spans = (interp.get("data_json") or {}).get("tag_spans", [])
    invalidate_interpretation_embedding(con, node_id, tag_spans)

    log_user_action(
        con,
        "edit",
        node_id,
        old_value={"narrative": old_narrative},
        new_value={"narrative": new_narrative},
    )
    increment_user_action_count(con)


def handle_reject_interpretation(
    con: duckdb.DuckDBPyConnection,
    interp: dict[str, Any],
    db_path: Optional[Path] = None,
) -> None:
    """Reject an interpretation: set node status and inference status to rejected."""
    node_id = interp["id"]
    _update_interpretation_status(con, node_id, "rejected", db_path=db_path)
    set_status(
        con,
        entity_id=str(node_id),
        entity_type=ENTITY_INTERPRETATION,
        stage=STAGE_INTERPRETATION,
        status=REJECTED,
    )
    log_user_action(con, "reject", node_id)
    increment_user_action_count(con)


def handle_defer_interpretation(
    con: duckdb.DuckDBPyConnection,
    interp: dict[str, Any],
) -> None:
    """Defer an interpretation: log action only, no status change."""
    log_user_action(con, "defer", interp["id"])
    increment_user_action_count(con)
