"""Generic inference status update helpers.

Provides :func:`mark_success` and :func:`mark_failure` for updating
inference_status after LLM inference. Used by all inference services
(code, theme, interpretation) to avoid duplicating status-update
logic across service modules.

Usage:
    from inference.status_updates import mark_success, mark_failure

    mark_success(con, exemplar_id, "exemplar", "code")
    mark_failure(con, exemplar_id, "No code generated")
"""

from utils.logging import get_logger

from .inference_status_crud import set_status
from .inference_status_types import GENERATED

logger = get_logger(__name__)


def mark_success(
    con,
    entity_id: int | str,
    entity_type: str,
    stage: str,
) -> None:
    """Mark an entity as successfully generated for a pipeline stage.

    Calls ``set_status(status=GENERATED)`` to record the success
    in the inference_status table. The entity's status changes from
    ``pending`` (or ``draft``) to ``generated``.

    Args:
        con: Active DuckDB connection.
        entity_id: Entity identifier (int or str, cast to str).
        entity_type: Entity type constant (e.g. ``"exemplar"``, ``"code"``).
        stage: Pipeline stage constant (e.g. ``"code"``, ``"theme"``).
    """
    set_status(
        con,
        entity_id=str(entity_id),
        entity_type=entity_type,
        stage=stage,
        status=GENERATED,
    )


def mark_failure(
    con,
    entity_id: int | str,
    error: str,
) -> None:
    """Log an inference failure for an entity; leave status as-is.

    The entity's inference_status remains ``pending`` (or ``draft``)
    so it will be retried in a subsequent run. The error is logged
    at ERROR level with structured context for debugging.

    Args:
        con: Active DuckDB connection (unused, kept for API consistency).
        entity_id: Entity identifier.
        error: Human-readable error description.
    """
    logger.error(
        "Inference failed for %s: %s",
        entity_id,
        error,
        extra={"entity_id": str(entity_id), "error": error},
    )
