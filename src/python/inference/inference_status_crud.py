"""Write operations for the inference_status table.

Provides upsert, draft-marking, and batch-insert functions for
tracking inference progress per entity per stage.
"""

from datetime import datetime, timezone
from typing import List, Tuple

import duckdb
from utils.logging import get_logger

from .inference_status_types import (
    DRAFT,
    GENERATED,
    INFERENCE_STATUS_DDL,
    _validate_params,
)

logger = get_logger(__name__)


def init_inference_status_table(con: duckdb.DuckDBPyConnection) -> None:
    """Create the ``inference_status`` table if it does not exist.

    Idempotent: safe to call multiple times.

    Args:
        con: Active DuckDB connection.

    Raises:
        duckdb.Error: If table creation fails.
    """
    con.execute(INFERENCE_STATUS_DDL)
    logger.debug("inference_status table ensured")


def set_status(
    con: duckdb.DuckDBPyConnection,
    entity_id: str,
    entity_type: str,
    stage: str,
    status: str,
) -> None:
    """Set the inference status for a single entity.

    Uses ``INSERT OR REPLACE``. ``last_attempt_at`` set to now when
    status is ``generated``. ``attempts`` incremented if row exists.

    Args:
        con: Active DuckDB connection.
        entity_id: Identifier for the entity.
        entity_type: Entity type constant.
        stage: Pipeline stage constant.
        status: Status constant.

    Raises:
        ValueError: If any argument is invalid.
        duckdb.Error: If the database operation fails.
    """
    _validate_params(entity_id, entity_type, stage, status)

    now = datetime.now(timezone.utc).isoformat() if status == GENERATED else None
    existing = con.execute(
        "SELECT attempts FROM inference_status "
        "WHERE entity_id = ? AND entity_type = ? AND stage = ?",
        [entity_id, entity_type, stage],
    ).fetchone()
    attempts = (existing[0] + 1) if existing else 1

    con.execute(
        """
        INSERT OR REPLACE INTO inference_status
            (entity_id, entity_type, stage, status, last_attempt_at, attempts)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        [entity_id, entity_type, stage, status, now, attempts],
    )
    logger.debug(
        "Inference status set",
        extra={
            "entity_id": entity_id,
            "entity_type": entity_type,
            "stage": stage,
            "status": status,
            "attempts": attempts,
        },
    )


def set_status_draft(
    con: duckdb.DuckDBPyConnection,
    entity_id: str,
    entity_type: str,
    stage: str,
) -> None:
    """Set the entity status to ``draft`` and increment attempts.

    Called when a code, theme, or interpretation is edited via HITL.

    Args:
        con: Active DuckDB connection.
        entity_id: Identifier for the entity.
        entity_type: Entity type constant.
        stage: Pipeline stage constant.
    """
    existing = con.execute(
        "SELECT attempts FROM inference_status "
        "WHERE entity_id = ? AND entity_type = ? AND stage = ?",
        [entity_id, entity_type, stage],
    ).fetchone()
    attempts = (existing[0] + 1) if existing else 1

    con.execute(
        """
        INSERT OR REPLACE INTO inference_status
            (entity_id, entity_type, stage, status, attempts)
        VALUES (?, ?, ?, ?, ?)
        """,
        [entity_id, entity_type, stage, DRAFT, attempts],
    )
    logger.debug(
        "Inference status set to draft",
        extra={
            "entity_id": entity_id,
            "entity_type": entity_type,
            "stage": stage,
            "attempts": attempts,
        },
    )


def batch_set_status(
    con: duckdb.DuckDBPyConnection,
    updates: List[Tuple[str, str, str, str]],
) -> None:
    """Bulk upsert inference statuses for multiple entities.

    Each tuple is ``(entity_id, entity_type, stage, status)``.

    Args:
        con: Active DuckDB connection.
        updates: List of (entity_id, entity_type, stage, status) tuples.

    Raises:
        ValueError: If any tuple is invalid.
        duckdb.Error: If the database operation fails.
    """
    now = datetime.now(timezone.utc).isoformat()

    for entity_id, entity_type, stage, status in updates:
        _validate_params(entity_id, entity_type, stage, status)
        ts = now if status == GENERATED else None
        existing = con.execute(
            "SELECT attempts FROM inference_status "
            "WHERE entity_id = ? AND entity_type = ? AND stage = ?",
            [entity_id, entity_type, stage],
        ).fetchone()
        attempts = (existing[0] + 1) if existing else 1
        con.execute(
            """
            INSERT OR REPLACE INTO inference_status
                (entity_id, entity_type, stage, status, last_attempt_at, attempts)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            [entity_id, entity_type, stage, status, ts, attempts],
        )

    logger.debug("Batch inference status updated", extra={"count": len(updates)})


__all__ = [
    "init_inference_status_table",
    "set_status",
    "set_status_draft",
    "batch_set_status",
]
