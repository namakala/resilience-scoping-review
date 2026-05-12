"""Schema migration engine and version progression."""

from pathlib import Path

import duckdb
from utils.logging import get_logger

from .duckdb_connection import get_schema_version
from .duckdb_schema import (
    _create_edges_table,
    _create_nodes_table,
    _create_session_state_table,
    _create_traversal_cache_table,
    _create_user_actions_table,
    _ensure_sequences,
)

logger = get_logger(__name__)


def migrate_schema(
    target_version: int,
    db_path: Path | None = None,
    con: duckdb.DuckDBPyConnection | None = None,
) -> None:
    """Migrate the database schema to the specified target version.

    Currently a no-op placeholder. As the schema evolves, this function will
    contain incremental migration logic (ALTER TABLE, ADD COLUMN, CREATE INDEX, etc.)
    that transforms an older schema_version to target_version.

    Migrations are applied incrementally: if current_version < target_version,
    each intermediate migration step runs in order. If current_version > target_version,
    downgrades are not supported (schema evolution is forward-only).

    Args:
        target_version: The desired schema version (integer ≥ 0).
        db_path: Path to DuckDB file. Used only if con is None.
        con: Optional existing DuckDB connection.

    Raises:
        ValueError: If target_version is less than current version.
    """
    close_after = False
    if con is None:
        from .duckdb_connection import get_connection

        con = get_connection(db_path)
        close_after = True

    try:
        current_version = get_schema_version(db_path=db_path, con=con)
        if current_version == target_version:
            logger.info(
                "Schema already at target version", extra={"version": target_version}
            )
            return

        if current_version > target_version:
            raise ValueError(
                f"Cannot downgrade schema from version {current_version} "
                f"to {target_version}. "
                "Schema evolution is forward-only."
            )

        # Apply migrations incrementally
        from_version = current_version
        while from_version < target_version:
            _apply_migration(con, from_version, from_version + 1)
            from_version += 1

        logger.info(
            "Schema migration complete",
            extra={"from": current_version, "to": target_version},
        )
    finally:
        if close_after and con:
            con.close()


def _apply_migration(
    con: duckdb.DuckDBPyConnection,
    from_version: int,
    to_version: int,
) -> None:
    """Apply a single migration step from from_version to to_version.

    This internal dispatcher contains the SQL required for each version jump.
    Add new migration blocks here when the schema evolves.

    Args:
        con: Active DuckDB connection.
        from_version: Current schema version.
        to_version: Target schema version (must be from_version + 1).

    Raises:
        NotImplementedError: If no migration exists for the given version jump.
    """
    if from_version == 0 and to_version == 1:
        # Ensure sequences exist before tables that use them
        _ensure_sequences(con)
        # Create all base tables (idempotent, safe to run even if partially exists)
        _create_nodes_table(con)
        _create_edges_table(con)
        _create_traversal_cache_table(con)
        _create_session_state_table(con)
        _create_user_actions_table(con)
        # Record new version
        from .duckdb_connection import _set_schema_version_if_missing

        _set_schema_version_if_missing(con, 1)
        logger.info("Applied migration 0→1: initial schema")
    else:
        raise NotImplementedError(
            f"No migration defined from version {from_version} to {to_version}"
        )
