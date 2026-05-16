"""Simple action handlers for interpretation review HITL CLI.

Provides ``handle_approve_interpretation``, ``handle_edit_interpretation``,
``handle_reject_interpretation``, and ``handle_defer_interpretation``.
"""

from pathlib import Path
from typing import Any, Optional

import duckdb
from inference.inference_status_crud import set_status, set_status_draft
from inference.inference_status_types import (
    ENTITY_INTERPRETATION,
    REJECTED,
    STAGE_INTERPRETATION,
)
from utils.logging import get_logger

from .approvals import approve_interpretation
from .invalidation import invalidate_interpretation_embedding
from .shared import (
    _log_and_finish,
    _update_node_definition,
    _update_node_name,
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

    Validates constraints, then delegates to ``approve_interpretation()``
    which finalises the interpretation, invalidates caches, and updates
    session counters.
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

    try:
        approve_interpretation(con, node_id, db_path=db_path)
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        logger.warning(
            "Interpretation approval failed",
            extra={"error": str(exc), "node_id": node_id},
        )


def handle_edit_interpretation(
    con: duckdb.DuckDBPyConnection,
    interp: dict[str, Any],
    db_path: Optional[Path] = None,
    new_narrative: str = "",
    new_name: str = "",
) -> None:
    """Edit an interpretation: update narrative and/or name,
    reset to draft, invalidate cache.

    Preserves ``tag`` and ``tag_spans`` — scope cannot be changed via edit.
    Refuses to edit an already-approved interpretation.
    """
    node_id = interp["id"]

    if interp.get("status") == "approved":
        console.print(
            "[red]Cannot edit an approved interpretation. "
            "Create a new interpretation instead.[/red]"
        )
        logger.warning(
            "Edit rejected: interpretation is approved",
            extra={"node_id": node_id},
        )
        return

    old_narrative = interp.get("narrative", "")
    old_name = interp.get("name", "")

    if not new_narrative.strip() and not new_name.strip():
        logger.warning("Edit aborted: both narrative and name are empty")
        return

    if new_narrative == old_narrative and (
        not new_name.strip() or new_name == old_name
    ):
        logger.info("Edit aborted: narrative and name unchanged")
        return

    old_value: dict[str, Any] = {}
    new_value: dict[str, Any] = {}

    if new_narrative.strip() and new_narrative != old_narrative:
        _update_node_definition(con, node_id, new_narrative, db_path=db_path)
        set_status_draft(
            con,
            entity_id=str(node_id),
            entity_type=ENTITY_INTERPRETATION,
            stage=STAGE_INTERPRETATION,
        )
        tag_spans = (interp.get("data_json") or {}).get("tag_spans", [])
        invalidate_interpretation_embedding(con, node_id, tag_spans)
        old_value["narrative"] = old_narrative
        new_value["narrative"] = new_narrative

    if new_name.strip() and new_name != old_name:
        _update_node_name(con, node_id, new_name, db_path=db_path)
        old_value["name"] = old_name
        new_value["name"] = new_name

    _log_and_finish(con, "edit", node_id, old_value, new_value)


def handle_reject_interpretation(
    con: duckdb.DuckDBPyConnection,
    interp: dict[str, Any],
    db_path: Optional[Path] = None,
) -> None:
    """Reject an interpretation: set node status and inference status to rejected.

    Refuses to reject an already-approved interpretation.
    """
    node_id = interp["id"]

    if interp.get("status") == "approved":
        console.print(
            "[red]Cannot reject an approved interpretation. "
            "Approved interpretations are final.[/red]"
        )
        logger.warning(
            "Reject rejected: interpretation is approved",
            extra={"node_id": node_id},
        )
        return

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
