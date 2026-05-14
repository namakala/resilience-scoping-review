"""Interpretation approval: finalize, invalidate caches, increment counters.

Provides ``approve_interpretation()`` which marks an interpretation as
approved, invalidates downstream caches, sets dirty flags, and updates
session counters.

References:
    Feature 51: interpretation-approval-finalizes
    ADR-011: Human-in-the-Loop Validation
"""

import json
from pathlib import Path
from typing import Any, Optional

import duckdb
from graph import sync_node
from graph.exceptions import ForeignKeyError
from inference.inference_status_crud import set_status
from inference.inference_status_types import (
    APPROVED,
    ENTITY_INTERPRETATION,
    STAGE_INTERPRETATION,
)
from ontology.invalidation import invalidate_cache_for_tag
from persistence.state_updates import (
    increment_approved_interpretation_count,
    update_dirty_flag,
)
from utils.logging import get_logger

from .user_action_log import log_user_action

logger = get_logger(__name__)

__all__ = ["approve_interpretation"]


def approve_interpretation(
    con: duckdb.DuckDBPyConnection,
    interp_id: int,
    db_path: Optional[Path] = None,
    user_id: str = "local-user",
) -> dict[str, Any]:
    """Approve an interpretation, finalizing it permanently.

    Validates the interpretation exists and is not already approved, then:
    - Sets node status to ``approved``
    - Syncs the in-memory graph
    - Invalidates traversal cache for every tag in ``tag_spans``
    - Sets dirty flags for every tag in ``tag_spans``
    - Sets inference status to ``APPROVED``
    - Increments ``approved_interpretation_count`` in session state
    - Logs a user action with old/new status

    Args:
        con: Active DuckDB connection.
        interp_id: Interpretation node ID.
        db_path: DuckDB path for graph sync operations.
        user_id: Researcher or session identifier for audit log.

    Returns:
        Dict with keys ``node_id``, ``old_status``, ``new_status``,
        ``tag_spans`` for introspection.

    Raises:
        ValueError: If interpretation not found or already approved.
        duckdb.Error: If a database operation fails.
    """
    row = con.execute(
        "SELECT status, data_json FROM nodes WHERE id = ? AND type = 'interpretation'",
        [interp_id],
    ).fetchone()

    if row is None:
        raise ValueError(f"Interpretation #{interp_id} not found.")

    old_status = row[0]
    if old_status == "approved":
        raise ValueError(f"Interpretation #{interp_id} is already approved.")

    dj_raw = row[1]
    dj: dict = json.loads(dj_raw) if dj_raw else {}
    tag_spans: list[str] = dj.get("tag_spans", [])

    con.execute(
        "UPDATE nodes SET status = 'approved', "
        "updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        [interp_id],
    )
    sync_node(interp_id, db_path)

    for tag in tag_spans:
        try:
            invalidate_cache_for_tag(
                tag, db_path=db_path, reason="interpretation_approval"
            )
        except (KeyError, ForeignKeyError) as exc:
            logger.warning(
                "Could not invalidate cache for tag; " "ontology DAG may not be loaded",
                extra={"tag": tag, "error": str(exc)},
            )
        update_dirty_flag(con, tag, True)

    set_status(
        con,
        entity_id=str(interp_id),
        entity_type=ENTITY_INTERPRETATION,
        stage=STAGE_INTERPRETATION,
        status=APPROVED,
    )

    increment_approved_interpretation_count(con)
    log_user_action(
        con,
        "approve",
        interp_id,
        old_value={"status": old_status},
        new_value={"status": "approved"},
        user_id=user_id,
    )

    logger.info(
        "Interpretation approved",
        extra={
            "interp_id": interp_id,
            "old_status": old_status,
            "tag_spans": tag_spans,
        },
    )

    return {
        "node_id": interp_id,
        "old_status": old_status,
        "new_status": "approved",
        "tag_spans": tag_spans,
    }
