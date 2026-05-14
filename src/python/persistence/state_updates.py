"""Atomic state field updates for the thematic analysis pipeline.

Provides setters and getters for individual state fields using the
load-modify-save pattern. All operations are atomic at the connection level
and respect validation rules defined in state_repository.

References:
    ADR-007 (Incremental Ontology Evolution): dirty-state propagation
"""

import json
from typing import Dict, Optional, cast

import duckdb
from persistence.state_repository import load_state, save_state
from utils.exceptions import StateError
from utils.logging import get_logger

logger = get_logger(__name__)


def update_dirty_flag(
    con: duckdb.DuckDBPyConnection, tag: str, dirty: bool = True
) -> None:
    """Set the dirty flag for a given tag.

    Loads the current state, updates the dirty flag for the specified tag,
    and saves it back. Tags with dots (e.g., "Problem.Cause") are handled
    as single keys in the dirty_flags dict.

    Args:
        con: Active DuckDB connection.
        tag: Tag name (e.g., "Problem.Cause").
        dirty: True to mark dirty, False to clear.

    Raises:
        StateError: If state load/save fails or tag is not a string.
    """
    if not isinstance(tag, str):
        raise StateError(f"Tag must be a string, got {type(tag).__name__}")

    state = load_state(con)
    dirty_flags = state.get("dirty_flags", {})
    dirty_flags[tag] = dirty
    state["dirty_flags"] = dirty_flags
    save_state(con, state)
    logger.debug("Dirty flag updated", extra={"tag": tag, "dirty": dirty})


def get_dirty_flags(con: duckdb.DuckDBPyConnection) -> Dict[str, bool]:
    """Get the current dirty_flags dict.

    Uses a direct JSON extraction query to avoid loading the full state.

    Args:
        con: Active DuckDB connection.

    Returns:
        Dict mapping tag names to boolean dirty flags. Empty dict if no state.
    """
    try:
        row = con.execute(
            "SELECT json_extract(value, '$.dirty_flags') "
            "FROM session_state "
            "WHERE key = ?",
            ["workflow"],
        ).fetchone()
    except duckdb.Error as exc:
        logger.error("Failed to extract dirty_flags", extra={"error": str(exc)})
        raise StateError(f"Database error reading dirty_flags: {exc}") from exc

    if row is None or row[0] is None:
        return {}

    try:
        return cast(Dict[str, bool], json.loads(row[0]))
    except (json.JSONDecodeError, TypeError) as exc:
        logger.warning(
            "Failed to parse dirty_flags; returning empty dict",
            extra={"error": str(exc)},
        )
        return {}


def set_current_stage(con: duckdb.DuckDBPyConnection, stage: int) -> None:
    """Set the current_stage field.

    Args:
        con: Active DuckDB connection.
        stage: Stage number (must be 1-10).

    Raises:
        StateError: If stage is out of range or state operation fails.
    """
    if not isinstance(stage, int) or isinstance(stage, bool) or not (1 <= stage <= 10):
        raise StateError(f"Stage must be an integer between 1 and 10, got {stage!r}")

    state = load_state(con)
    state["current_stage"] = stage
    save_state(con, state)
    logger.debug("Current stage set", extra={"stage": stage})


def increment_user_action_count(con: duckdb.DuckDBPyConnection, delta: int = 1) -> None:
    """Increment the user_action_count by delta.

    Args:
        con: Active DuckDB connection.
        delta: Amount to increment (must be positive).

    Raises:
        StateError: If delta is not positive or state operation fails.
    """
    if not isinstance(delta, int) or isinstance(delta, bool) or delta <= 0:
        raise StateError(f"delta must be a positive integer, got {delta!r}")

    state = load_state(con)
    state["user_action_count"] = state.get("user_action_count", 0) + delta
    save_state(con, state)
    logger.debug("User action count incremented", extra={"delta": delta})


def increment_approved_interpretation_count(
    con: duckdb.DuckDBPyConnection, delta: int = 1
) -> None:
    """Increment the approved_interpretation_count by delta.

    Extra keys beyond the five required state fields are allowed and
    preserved by the state validator.

    Args:
        con: Active DuckDB connection.
        delta: Amount to increment (must be positive).

    Raises:
        StateError: If delta is not positive or state operation fails.
    """
    if not isinstance(delta, int) or isinstance(delta, bool) or delta <= 0:
        raise StateError(f"delta must be a positive integer, got {delta!r}")

    state = load_state(con)
    state["approved_interpretation_count"] = (
        state.get("approved_interpretation_count", 0) + delta
    )
    save_state(con, state)
    logger.debug("Approved interpretation count incremented", extra={"delta": delta})


def set_config_version(con: duckdb.DuckDBPyConnection, version: str) -> None:
    """Set the config_version string.

    Args:
        con: Active DuckDB connection.
        version: Configuration version string (e.g., a SHA-256 hash prefix).

    Raises:
        StateError: If state operation fails.
    """
    if not isinstance(version, str):
        raise StateError(
            f"config_version must be a string, got {type(version).__name__}"
        )

    state = load_state(con)
    state["config_version"] = version
    save_state(con, state)
    logger.debug("Config version set", extra={"version": version})


def set_last_checkpoint(
    con: duckdb.DuckDBPyConnection, timestamp: Optional[str] = None
) -> None:
    """Set the last_checkpoint timestamp.

    Args:
        con: Active DuckDB connection.
        timestamp: ISO 8601 formatted timestamp string. If None, uses current UTC time.

    Raises:
        StateError: If state operation fails.
    """
    from datetime import datetime, timezone

    if timestamp is None:
        timestamp = datetime.now(timezone.utc).isoformat()
    if not isinstance(timestamp, str):
        raise StateError(f"timestamp must be a string, got {type(timestamp).__name__}")

    state = load_state(con)
    state["last_checkpoint"] = timestamp
    save_state(con, state)
    logger.debug("Last checkpoint set", extra={"timestamp": timestamp})
