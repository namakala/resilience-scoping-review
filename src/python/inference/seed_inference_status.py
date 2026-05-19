"""Seed inference_status with pending exemplars for code inference.

Inserts all exemplar IDs into the ``inference_status`` table with
``status='pending'`` for the ``'code'`` stage so that
:func:`code_inference.infer_codes` finds them.

Idempotent: uses ``INSERT OR IGNORE``, so re-running is safe
(resumes without resetting already-processed exemplars).
"""

from __future__ import annotations

import duckdb
from persistence.loaders import load_exemplars
from utils.logging import get_logger

from .inference_status_types import ENTITY_EXEMPLAR, PENDING, STAGE_CODE

logger = get_logger(__name__)


def seed_pending_exemplars(con: duckdb.DuckDBPyConnection) -> int:
    """Insert all exemplar IDs into ``inference_status`` as pending.

    Must be called after exemplars are loaded (stage 1) and before
    code inference (stage 4).  Idempotent — exemplars already in the
    table are left untouched regardless of their current status.

    Args:
        con: Active DuckDB connection.

    Returns:
        Number of exemplar IDs processed (not necessarily newly inserted).
        Zero if no exemplars exist.
    """
    lf = load_exemplars().select(["id"])
    ids: list[str] = [str(row["id"]) for row in lf.collect().iter_rows(named=True)]

    if not ids:
        logger.info("No exemplars to seed for code inference")
        return 0

    con.executemany(
        "INSERT OR IGNORE INTO inference_status "
        "(entity_id, entity_type, stage, status) "
        "VALUES (?, ?, ?, ?)",
        [(eid, ENTITY_EXEMPLAR, STAGE_CODE, PENDING) for eid in ids],
    )

    logger.info(
        "Seeded %d pending exemplars for code inference",
        len(ids),
        extra={"total_exemplars": len(ids)},
    )
    return len(ids)


__all__ = ["seed_pending_exemplars"]
