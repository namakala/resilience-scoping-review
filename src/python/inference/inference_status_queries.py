"""Read/query operations and validation for the inference_status table.

Provides pending-item filtering, single-row debug lookups, aggregate
summaries, table reset, and argument validation.
"""

from typing import Any, List, Optional

import duckdb
from utils.logging import get_logger

from .inference_status_types import ALL_STAGES, ALL_STATUSES

logger = get_logger(__name__)


def get_pending_items(
    con: duckdb.DuckDBPyConnection,
    stage: str,
    tag: Optional[str] = None,
    tags: Optional[list[str]] = None,
) -> List[str]:
    """Return entity IDs needing inference for the given stage.

    Only items with status ``pending`` or ``draft`` are returned.
    If *tag* is provided, joins against the exemplars parquet to
    filter by ontology tag.  *tags* (plural) filters for multiple
    tags simultaneously.  *tag* and *tags* are mutually exclusive.

    Args:
        con: Active DuckDB connection.
        stage: Pipeline stage constant.
        tag: Optional single ontology tag for filtering.
        tags: Optional list of ontology tags for filtering.

    Returns:
        List of entity ID strings.

    Raises:
        ValueError: If stage is invalid, or both *tag* and *tags* given.
        duckdb.Error: If the query fails.
    """
    if stage not in ALL_STAGES:
        raise ValueError(
            f"Invalid stage {stage!r}. Must be one of {sorted(ALL_STAGES)}"
        )

    if tag is not None and tags is not None:
        raise ValueError("Provide either 'tag' or 'tags', not both")

    if tag:
        rows = con.execute(
            """
            SELECT i.entity_id
            FROM inference_status i
            WHERE i.stage = ?
              AND i.status IN ('pending', 'draft')
              AND CAST(i.entity_id AS BIGINT) IN (
                  SELECT id FROM read_parquet('data/processed/exemplars.parquet')
                  WHERE tag = ?
              )
            ORDER BY i.entity_id
            """,
            [stage, tag],
        ).fetchall()
    elif tags:
        rows = con.execute(
            """
            SELECT i.entity_id
            FROM inference_status i
            WHERE i.stage = ?
              AND i.status IN ('pending', 'draft')
              AND CAST(i.entity_id AS BIGINT) IN (
                  SELECT id FROM read_parquet('data/processed/exemplars.parquet')
                  WHERE tag IN ?
              )
            ORDER BY i.entity_id
            """,
            [stage, tags],
        ).fetchall()
    else:
        rows = con.execute(
            """
            SELECT entity_id
            FROM inference_status
            WHERE stage = ? AND status IN ('pending', 'draft')
            ORDER BY entity_id
            """,
            [stage],
        ).fetchall()

    return [row[0] for row in rows]


def get_status(
    con: duckdb.DuckDBPyConnection,
    entity_id: str,
    entity_type: str,
    stage: str,
) -> Optional[dict[str, Any]]:
    """Query a single inference status row for debugging.

    Returns a dict with keys (entity_id, entity_type, stage, status,
    last_attempt_at, attempts) or None if not found.
    """
    row = con.execute(
        """
        SELECT entity_id, entity_type, stage, status,
               last_attempt_at, attempts
        FROM inference_status
        WHERE entity_id = ? AND entity_type = ? AND stage = ?
        """,
        [entity_id, entity_type, stage],
    ).fetchone()

    if row is None:
        return None

    return {
        "entity_id": row[0],
        "entity_type": row[1],
        "stage": row[2],
        "status": row[3],
        "last_attempt_at": row[4],
        "attempts": row[5],
    }


def reset_inference_status(con: duckdb.DuckDBPyConnection) -> None:
    """Delete all rows from ``inference_status`` (full reset).

    Args:
        con: Active DuckDB connection.
    """
    con.execute("DELETE FROM inference_status")
    logger.info("Inference status table reset")


def get_stage_summary(
    con: duckdb.DuckDBPyConnection,
    stage: str,
) -> dict[str, int]:
    """Return aggregate counts by status for a given stage.

    Returns a dict like ``{"pending": 5, "generated": 12, ...}`` with
    all status keys present (zero counts for missing statuses).
    """
    rows = con.execute(
        """
        SELECT status, COUNT(*) as cnt
        FROM inference_status
        WHERE stage = ?
        GROUP BY status
        """,
        [stage],
    ).fetchall()

    summary: dict[str, int] = {s: 0 for s in ALL_STATUSES}
    for status, cnt in rows:
        summary[status] = cnt
    return summary


__all__ = [
    "get_pending_items",
    "get_status",
    "reset_inference_status",
    "get_stage_summary",
]
