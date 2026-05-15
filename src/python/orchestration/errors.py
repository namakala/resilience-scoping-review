"""Exit code constants, database corruption recovery, and fatal error handling.

Provides the central error-handling primitives for the orchestration
layer: exit codes (0-4), DuckDB integrity checking with schema-only
rebuild from Parquet, and logged graceful degradation on unhandled
exceptions.
"""

from __future__ import annotations

from typing import Any

import duckdb
from persistence.duckdb_connection import get_connection
from persistence.duckdb_init import initialize_database
from utils.logging import get_logger

logger = get_logger(__name__)

# ── Exit codes ──────────────────────────────────────────────────────

EXIT_SUCCESS: int = 0
EXIT_USER_INTERRUPT: int = 1
EXIT_CONFIG_ERROR: int = 2
EXIT_STORAGE_CORRUPTION: int = 3
EXIT_API_FAILURE: int = 4

# ── Integrity check ─────────────────────────────────────────────────


def check_integrity(
    con: duckdb.DuckDBPyConnection | None = None,
    db_path: str | None = None,
) -> bool:
    """Run ``PRAGMA integrity_check`` on the DuckDB database.

    Args:
        con: An existing connection.  If *None* a temporary connection
            to *db_path* is opened and closed.
        db_path: Path to the DuckDB file.  Required when *con* is None.

    Returns:
        ``True`` if integrity check passes, ``False`` if corruption
        is detected.
    """
    close_after = False
    if con is None:
        if db_path is None:
            logger.error("check_integrity requires con or db_path")
            return False
        try:
            con = get_connection(db_path)  # type: ignore[arg-type]
            close_after = True
        except duckdb.Error as exc:
            logger.error(
                "Cannot open database for integrity check",
                extra={"error": str(exc)},
            )
            return False

    try:
        row = con.execute("PRAGMA integrity_check").fetchone()
        ok: bool = row is not None and bool(row[0] == "ok")
        if ok:
            logger.info("DuckDB integrity check passed")
        else:
            logger.warning(
                "DuckDB integrity check FAILED",
                extra={"result": str(row[0]) if row else "None"},
            )
        return ok
    except duckdb.Error as exc:
        logger.error(
            "Integrity check query failed",
            extra={"error": str(exc)},
        )
        return False
    finally:
        if close_after:
            con.close()


# ── Database rebuild ────────────────────────────────────────────────

_REBUILD_TABLES: list[str] = [
    "invalidation_log",
    "node_cache",
    "embedding_cache",
    "inference_status",
    "user_actions",
    "traversal_cache",
    "edges",
    "nodes",
    "session_state",
]

_REBUILD_SEQUENCES: list[str] = [
    "il_seq",
    "ua_seq",
    "nodes_id_seq",
]


def rebuild_database(con: duckdb.DuckDBPyConnection) -> None:
    """Drop all application tables and recreate the schema from scratch.

    Does **not** touch Parquet artifacts on disk.  After rebuild the
    database is empty except for the schema skeleton — the next
    pipeline run will start from stage 1 (load) and repopulate from
    Parquet.

    Args:
        con: Active DuckDB connection (caller manages lifecycle).

    Raises:
        duckdb.Error: If any DROP or CREATE operation fails.
    """
    logger.warning("Starting database rebuild — all tables will be dropped")

    for table in _REBUILD_TABLES:
        try:
            con.execute(f"DROP TABLE IF EXISTS {table}")
            logger.debug("Dropped table %s", table)
        except duckdb.Error as exc:
            logger.error(
                "Failed to drop table %s",
                table,
                extra={"error": str(exc)},
            )
            raise

    for seq in _REBUILD_SEQUENCES:
        try:
            con.execute(f"DROP SEQUENCE IF EXISTS {seq}")
            logger.debug("Dropped sequence %s", seq)
        except duckdb.Error as exc:
            logger.error(
                "Failed to drop sequence %s",
                seq,
                extra={"error": str(exc)},
            )
            raise

    logger.info("All tables dropped; recreating schema")
    initialize_database(con=con)
    logger.info("Database rebuild complete — schema recreated from scratch")


# ── Fatal error handler ─────────────────────────────────────────────


def handle_fatal_error(
    exc: BaseException,
    exit_code: int = EXIT_API_FAILURE,
    con: duckdb.DuckDBPyConnection | None = None,
    state: Any = None,
) -> int:
    """Log an unrecoverable error and return an exit code.

    Attempts to save workflow state if a connection and state are
    available, then logs the full stack trace with an ``error_type``
    structured field.

    Args:
        exc: The exception that caused the failure.
        exit_code: Exit code to return (default ``EXIT_API_FAILURE``).
        con: Optional DuckDB connection for state persistence.
        state: Optional workflow state dict/object to persist.

    Returns:
        The *exit_code* suitable for ``sys.exit()`` or ``main()``.
    """
    error_type = type(exc).__name__

    if con is not None and state is not None:
        try:
            from persistence.state_repository import save_state

            if hasattr(state, "to_state_dict"):
                state_dict = state.to_state_dict()
            elif isinstance(state, dict):
                state_dict = state
            else:
                state_dict = None

            if state_dict:
                save_state(con, state_dict)
                logger.debug("State saved before fatal error handler")
        except Exception as save_err:
            logger.warning(
                "Could not save state during fatal error handling",
                extra={"error": str(save_err)},
            )

    logger.error(
        "Unhandled %s: %s",
        error_type,
        exc,
        exc_info=True,
        extra={"error_type": error_type},
    )
    return exit_code


__all__ = [
    "EXIT_SUCCESS",
    "EXIT_USER_INTERRUPT",
    "EXIT_CONFIG_ERROR",
    "EXIT_STORAGE_CORRUPTION",
    "EXIT_API_FAILURE",
    "check_integrity",
    "rebuild_database",
    "handle_fatal_error",
]
