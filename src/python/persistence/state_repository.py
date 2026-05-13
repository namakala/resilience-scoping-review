"""Database persistence operations for workflow state."""

import copy
import json
from datetime import datetime, timezone
from typing import Any, Dict

import duckdb
from persistence.state_constants import DEFAULT_STATE, WORKFLOW_KEY
from persistence.state_serialization import _serialize
from persistence.state_validator import validate_state
from utils.exceptions import StateError
from utils.logging import get_logger

logger = get_logger(__name__)


def load_state(con: duckdb.DuckDBPyConnection) -> Dict[str, Any]:
    """Load the workflow state from the session_state table.

    Reads the JSON value stored under the 'workflow' key, deserializes it,
    fills in defaults for any missing keys, and validates the result.
    Returns the default initial state if no row exists.

    Args:
        con: Active DuckDB connection.

    Returns:
        Workflow state dictionary.

    Raises:
        StateError: If stored state fails validation (malformed JSON or invalid values).
        duckdb.Error: If the database query fails.
    """
    try:
        row = con.execute(
            "SELECT value FROM session_state WHERE key = ?", [WORKFLOW_KEY]
        ).fetchone()
    except duckdb.Error as exc:
        logger.error("Failed to query session_state", extra={"error": str(exc)})
        raise StateError(f"Database error loading state: {exc}") from exc

    if row is None:
        logger.debug("No workflow state found; returning default initial state")
        return copy.deepcopy(DEFAULT_STATE)

    json_str = row[0]
    try:
        state = json.loads(json_str)
    except json.JSONDecodeError as exc:
        logger.error("Malformed JSON in workflow state", extra={"error": str(exc)})
        raise StateError("Malformed JSON in workflow state") from exc

    if not isinstance(state, dict):
        raise StateError(
            f"Expected workflow state to be a dict, got {type(state).__name__}"
        )

    # Fill in defaults for any missing required keys
    for key, default_val in DEFAULT_STATE.items():
        state.setdefault(key, default_val)

    validate_state(state)
    logger.debug(
        "State loaded successfully",
        extra={"stage": state.get("current_stage")},
    )
    return state


def save_state(con: duckdb.DuckDBPyConnection, state: Dict[str, Any]) -> None:
    """Save the workflow state to the session_state table (upsert).

    Validates the state, serializes it to JSON, and stores it under the
    'workflow' key with type 'dict'. Sets last_checkpoint to the current
    UTC time only if it is not already set.

    Args:
        con: Active DuckDB connection.
        state: Workflow state dictionary to persist.

    Raises:
        StateError: If state validation fails.
        duckdb.Error: If the database operation fails.
    """
    # Fill defaults for any missing required keys before validation
    state = dict(state)
    for key, default_val in DEFAULT_STATE.items():
        state.setdefault(key, default_val)

    validate_state(state)

    # Set checkpoint timestamp only if not already set
    if state.get("last_checkpoint") is None:
        state["last_checkpoint"] = datetime.now(timezone.utc).isoformat()

    json_str, _ = _serialize(state)

    try:
        con.execute(
            """
            INSERT OR REPLACE INTO session_state (key, value, type)
            VALUES (?, ?, ?)
            """,
            [WORKFLOW_KEY, json_str, "dict"],
        )
        con.commit()
    except duckdb.Error as exc:
        logger.error("Failed to save workflow state", extra={"error": str(exc)})
        raise StateError(f"Database error saving state: {exc}") from exc

    logger.debug(
        "Workflow state saved",
        extra={"stage": state.get("current_stage")},
    )


def reset_state(con: duckdb.DuckDBPyConnection) -> None:
    """Reset workflow state by deleting all rows from session_state.

    This performs a full table wipe as specified in plan 64 (--reset flag).
    The schema_version row and any other keys are also removed.

    Args:
        con: Active DuckDB connection.

    Raises:
        duckdb.Error: If the database operation fails.
    """
    try:
        con.execute("DELETE FROM session_state")
        con.commit()
    except duckdb.Error as exc:
        logger.error("Failed to reset session_state", extra={"error": str(exc)})
        raise exc

    logger.info("Session state reset (full table wipe)")
