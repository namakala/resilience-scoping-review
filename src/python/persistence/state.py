"""Workflow state persistence operations for the thematic analysis pipeline.

Provides load_state, save_state, reset_state, and atomic setters for
individual state fields (dirty flags, stage, checkpoint, etc.).
All workflow state is stored as a single JSON object under the key 'workflow'
in the session_state table.

References:
    ADR-007 (Incremental Ontology Evolution): dirty-state propagation
    Feature 10 (session-state-manager): state persistence spec
"""

from __future__ import annotations

import copy
import json
from datetime import datetime, timezone
from typing import Any, Dict, Optional, cast

import duckdb
from utils.exceptions import StateError
from utils.logging import get_logger

logger = get_logger(__name__)

# ── Constants ────────────────────────────────────────────────────────────────

WORKFLOW_KEY = "workflow"

DEFAULT_STATE: Dict[str, Any] = {
    "current_stage": 1,
    "dirty_flags": {},
    "last_checkpoint": None,
    "config_version": "",
    "user_action_count": 0,
}


# ── Serialization helpers ────────────────────────────────────────────────────


def _serialize(obj: Any) -> tuple[str, str]:
    """Serialize a Python object to JSON string with type hint.

    Args:
        obj: Python object to serialize (int, float, str, bool, dict, list, None).

    Returns:
        Tuple of (json_string, type_hint).

    Raises:
        StateError: If the object type is not JSON-serializable.
    """
    if obj is None:
        return "null", "null"
    if isinstance(obj, bool):
        return json.dumps(obj), "bool"
    if isinstance(obj, int):
        return json.dumps(obj), "int"
    if isinstance(obj, float):
        return json.dumps(obj), "float"
    if isinstance(obj, str):
        return json.dumps(obj), "str"
    if isinstance(obj, dict):
        return json.dumps(obj, ensure_ascii=False), "dict"
    if isinstance(obj, list):
        return json.dumps(obj, ensure_ascii=False), "list"
    raise StateError(
        f"Unsupported state value type: {type(obj).__name__}. "
        "Only int, float, str, bool, dict, list, and None are supported."
    )


def _deserialize(json_str: str, type_hint: str) -> Any:
    """Deserialize a JSON string back to a Python object.

    Args:
        json_str: JSON-encoded string.
        type_hint: Type hint stored alongside the value ('int', 'str', 'dict', etc.).

    Returns:
        Deserialized Python object.

    Raises:
        StateError: If deserialization fails or type mismatch detected.
    """
    try:
        obj = json.loads(json_str)
    except json.JSONDecodeError as exc:
        raise StateError(f"Malformed JSON in state value: {exc}") from exc

    # Type coercion based on hint
    if type_hint == "int" and isinstance(obj, int):
        return obj
    if type_hint == "float" and isinstance(obj, (int, float)):
        return float(obj) if type_hint == "float" else obj
    if type_hint == "bool" and isinstance(obj, bool):
        return obj
    if type_hint == "str" and isinstance(obj, str):
        return obj
    if type_hint in ("dict",) and isinstance(obj, dict):
        return obj
    if type_hint in ("list",) and isinstance(obj, list):
        return obj
    if type_hint == "null" and obj is None:
        return None

    # For 'workflow' key we always store as 'dict'
    return obj


# ── Validation ───────────────────────────────────────────────────────────────


def validate_state(state: Dict[str, Any]) -> None:
    """Validate the workflow state dictionary.

    Checks required keys, types, and value constraints. Extra keys beyond
    the five required fields are allowed and preserved.

    Args:
        state: Workflow state dictionary to validate.

    Raises:
        StateError: If validation fails (invalid stage, malformed dirty_flags, etc.).
    """
    # current_stage: int in [1, 10]
    cs = state.get("current_stage")
    if not isinstance(cs, int) or isinstance(cs, bool) or not (1 <= cs <= 10):
        raise StateError(
            f"Invalid current_stage: {cs}. Must be an integer between 1 and 10."
        )

    # dirty_flags: dict with string keys and boolean values
    df = state.get("dirty_flags")
    if not isinstance(df, dict):
        raise StateError(f"dirty_flags must be a dict, got {type(df).__name__}")
    for tag, dirty in df.items():
        if not isinstance(tag, str):
            raise StateError(
                f"dirty_flags key must be str, got {type(tag).__name__}: {tag!r}"
            )
        if not isinstance(dirty, bool):
            raise StateError(
                f"dirty_flags['{tag}'] must be bool, got {type(dirty).__name__}"
            )

    # last_checkpoint: None or string
    lc = state.get("last_checkpoint")
    if lc is not None and not isinstance(lc, str):
        raise StateError(
            f"last_checkpoint must be a string or None, got {type(lc).__name__}"
        )

    # config_version: string
    cv = state.get("config_version")
    if not isinstance(cv, str):
        raise StateError(f"config_version must be a string, got {type(cv).__name__}")

    # user_action_count: non-negative int
    uac = state.get("user_action_count")
    if not isinstance(uac, int) or isinstance(uac, bool) or uac < 0:
        raise StateError(f"user_action_count must be a non-negative int, got {uac!r}")

    logger.debug("State validation passed", extra={"stage": cs})


# ── Core CRUD operations ─────────────────────────────────────────────────────


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


# ── Atomic partial updates ───────────────────────────────────────────────────


def _ensure_workflow_row(con: duckdb.DuckDBPyConnection) -> None:
    """Ensure the workflow key row exists; insert default state if missing.

    Uses INSERT ... SELECT WHERE NOT EXISTS for atomicity.

    Args:
        con: Active DuckDB connection.
    """
    con.execute(
        """
        INSERT INTO session_state (key, value, type)
        SELECT ?, ?, 'dict'
        WHERE NOT EXISTS (SELECT 1 FROM session_state WHERE key = ?)
        """,
        [
            WORKFLOW_KEY,
            json.dumps(DEFAULT_STATE, ensure_ascii=False),
            WORKFLOW_KEY,
        ],
    )


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
        StateError: If state load/save fails.
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
            [WORKFLOW_KEY],
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
    if timestamp is None:
        timestamp = datetime.now(timezone.utc).isoformat()
    if not isinstance(timestamp, str):
        raise StateError(f"timestamp must be a string, got {type(timestamp).__name__}")

    state = load_state(con)
    state["last_checkpoint"] = timestamp
    save_state(con, state)
    logger.debug("Last checkpoint set", extra={"timestamp": timestamp})
