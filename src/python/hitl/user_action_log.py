"""CRUD for the user_actions audit table.

Provides ``log_user_action()`` to insert a row into the ``user_actions``
table with automatic sequence-based ID and ISO timestamp.
"""

import json
from typing import Any, Optional

import duckdb
from utils.logging import get_logger

logger = get_logger(__name__)

__all__ = ["log_user_action"]

VALID_ACTIONS = frozenset({"approve", "edit", "merge", "reject", "defer", "split"})


def log_user_action(
    con: duckdb.DuckDBPyConnection,
    action_type: str,
    entity_id: int,
    old_value: Optional[dict[str, Any]] = None,
    new_value: Optional[dict[str, Any]] = None,
    user_id: str = "local-user",
) -> int:
    """Insert a row into the ``user_actions`` table and return the action ID.

    Args:
        con: Active DuckDB connection.
        action_type: One of ``approve``, ``edit``, ``merge``, ``reject``,
            ``defer``, ``split``.
        entity_id: Affected graph node ID.
        old_value: Optional JSON-serializable snapshot of prior state.
        new_value: Optional JSON-serializable snapshot of new state.
        user_id: Researcher or session identifier.

    Returns:
        Auto-generated ``action_id``.

    Raises:
        ValueError: If *action_type* is not valid.
        duckdb.Error: If the database operation fails.
    """
    if action_type not in VALID_ACTIONS:
        raise ValueError(
            f"Invalid action_type {action_type!r}. "
            f"Must be one of {sorted(VALID_ACTIONS)}"
        )

    old_str = json.dumps(old_value, ensure_ascii=False) if old_value else None
    new_str = json.dumps(new_value, ensure_ascii=False) if new_value else None

    con.execute(
        """
        INSERT INTO user_actions
            (action_id, action_type, entity_id, old_value, new_value, user_id)
        VALUES (nextval('ua_seq'), ?, ?, ?, ?, ?)
        """,
        [action_type, entity_id, old_str, new_str, user_id],
    )

    action_id = int(con.execute("SELECT currval('ua_seq')").fetchone()[0])
    logger.debug(
        "User action logged",
        extra={
            "action_id": action_id,
            "action_type": action_type,
            "entity_id": entity_id,
        },
    )
    return action_id
