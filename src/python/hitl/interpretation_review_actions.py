"""Simple action handlers for interpretation review HITL CLI.

Provides ``handle_approve_interpretation``, ``handle_edit_interpretation``,
``handle_reject_interpretation``, and ``handle_defer_interpretation``.
"""

from pathlib import Path
from typing import Any, Optional

import duckdb
from inference.inference_status_crud import set_status, set_status_draft
from inference.inference_status_types import (
    APPROVED,
    ENTITY_INTERPRETATION,
    REJECTED,
    STAGE_INTERPRETATION,
)
from utils.logging import get_logger

from .invalidation import invalidate_interpretation_embedding
from .shared import (
    _log_and_finish,
    _update_node_definition,
    _update_node_status,
    console,
)

logger = get_logger(__name__)

__all__ = [
    "handle_approve_interpretation",
    "handle_edit_interpretation",
    "handle_reject_interpretation",
    "handle_defer_interpretation",
]


# ── Action handlers ────────────────────────────────────────────────


def handle_approve_interpretation(
    con: duckdb.DuckDBPyConnection,
    interp: dict[str, Any],
    db_path: Optional[Path] = None,
) -> None:
    """Approve an interpretation.

    Validate constraints, set node status and inference status.
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
        console.print(f"[red]Constraint violation: {exc}[/red]")
        logger.warning(
            "Interpretation approve rejected by constraint",
            extra={"error": str(exc), "constraint_type": exc.code},
        )
        return

    _update_node_status(con, node_id, "approved", db_path=db_path)
    set_status(
        con,
        entity_id=str(node_id),
        entity_type=ENTITY_INTERPRETATION,
        stage=STAGE_INTERPRETATION,
        status=APPROVED,
    )
    _log_and_finish(con, "approve", node_id)


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

    _update_node_definition(con, node_id, new_narrative, db_path=db_path)
    set_status_draft(
        con,
        entity_id=str(node_id),
        entity_type=ENTITY_INTERPRETATION,
        stage=STAGE_INTERPRETATION,
    )

    tag_spans = (interp.get("data_json") or {}).get("tag_spans", [])
    invalidate_interpretation_embedding(con, node_id, tag_spans)

    _log_and_finish(
        con,
        "edit",
        node_id,
        old_value={"narrative": old_narrative},
        new_value={"narrative": new_narrative},
    )


def handle_reject_interpretation(
    con: duckdb.DuckDBPyConnection,
    interp: dict[str, Any],
    db_path: Optional[Path] = None,
) -> None:
    """Reject an interpretation: set node status and inference status to rejected."""
    node_id = interp["id"]
    _update_node_status(con, node_id, "rejected", db_path=db_path)
    set_status(
        con,
        entity_id=str(node_id),
        entity_type=ENTITY_INTERPRETATION,
        stage=STAGE_INTERPRETATION,
        status=REJECTED,
    )
    _log_and_finish(con, "reject", node_id)


def handle_defer_interpretation(
    con: duckdb.DuckDBPyConnection,
    interp: dict[str, Any],
) -> None:
    """Defer an interpretation: log action only, no status change."""
    _log_and_finish(con, "defer", interp["id"])
