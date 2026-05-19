"""Shared utilities for HITL review modules.

Provides ``console`` singleton, node update helpers, and common action
patterns used across code, theme, and interpretation review.
"""

import contextlib
import json
from pathlib import Path
from typing import Any, Iterator, Optional

import duckdb
from graph import sync_node
from rich.console import Console
from utils.logging import get_logger

logger = get_logger(__name__)


class _TUIAwareConsole:
    """Console wrapper that can be silenced during TUI sessions.

    Modules that ``from .shared import console`` hold a reference to a
    single ``_TUIAwareConsole`` instance.  When the ``tui_mode()``
    context manager is active, ``print()`` calls are silently dropped;
    all other ``Console`` methods pass through as normal.
    """

    def __init__(self) -> None:
        self._console = Console()
        self._tui_active = False

    def print(self, *args: Any, **kwargs: Any) -> None:
        if not self._tui_active:
            self._console.print(*args, **kwargs)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._console, name)


console = _TUIAwareConsole()


@contextlib.contextmanager
def tui_mode() -> Iterator[None]:
    """Silence ``console.print()`` during TUI operation.

    Sets the internal ``_tui_active`` flag on the shared
    ``_TUIAwareConsole`` instance so that ``console.print()`` becomes a
    no-op, preventing shared action handlers from corrupting Textual's
    alternate screen.  Restores on exit.
    """
    console._tui_active = True
    try:
        yield
    finally:
        console._tui_active = False


def _update_node_status(
    con: duckdb.DuckDBPyConnection,
    node_id: int,
    new_status: str,
    db_path: Optional[Path] = None,
) -> None:
    """Update node status in DuckDB and sync the in-memory graph."""
    con.execute(
        "UPDATE nodes SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        [new_status, node_id],
    )
    sync_node(node_id, db_path)


def _update_node_name(
    con: duckdb.DuckDBPyConnection,
    node_id: int,
    new_name: str,
    db_path: Optional[Path] = None,
) -> None:
    """Update node name in DuckDB and sync the in-memory graph."""
    con.execute(
        "UPDATE nodes SET name = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        [new_name, node_id],
    )
    sync_node(node_id, db_path)


def _update_node_definition(
    con: duckdb.DuckDBPyConnection,
    node_id: int,
    new_definition: str,
    db_path: Optional[Path] = None,
) -> None:
    """Update node definition and reset status to draft, then sync graph."""
    con.execute(
        "UPDATE nodes SET definition = ?, status = 'draft', "
        "updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        [new_definition, node_id],
    )
    sync_node(node_id, db_path)


def _update_node_data_json(
    con: duckdb.DuckDBPyConnection,
    node_id: int,
    new_data_json: dict[str, Any],
    db_path: Optional[Path] = None,
) -> None:
    """Update node data_json in DuckDB and sync the in-memory graph."""
    con.execute(
        "UPDATE nodes SET data_json = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        [json.dumps(new_data_json, ensure_ascii=False), node_id],
    )
    sync_node(node_id, db_path)


def _log_and_finish(
    con: duckdb.DuckDBPyConnection,
    action_type: str,
    entity_id: int,
    old_value: Optional[dict[str, Any]] = None,
    new_value: Optional[dict[str, Any]] = None,
) -> None:
    """Log a user action and increment the action counter."""
    from persistence.state_updates import increment_user_action_count

    from .user_action_log import log_user_action

    log_user_action(con, action_type, entity_id, old_value, new_value)
    increment_user_action_count(con)


def handle_defer_entity(
    con: duckdb.DuckDBPyConnection,
    entity: dict[str, Any],
) -> None:
    """Defer an entity: log action only, no status change."""
    _log_and_finish(con, "defer", entity["id"])


__all__ = [
    "console",
    "tui_mode",
    "_update_node_status",
    "_update_node_name",
    "_update_node_definition",
    "_update_node_data_json",
    "_log_and_finish",
    "handle_defer_entity",
]
