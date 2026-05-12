"""Orchestrates DuckDB initialization: applies migrations and creates schema."""

from pathlib import Path

import duckdb
from utils.logging import get_logger

# Import internal helpers from specialized modules (must be at top for flake8)
from .duckdb_connection import (
    DEFAULT_DB_PATH,
    SCHEMA_VERSION,
    get_connection,
    get_schema_version,
)
from .duckdb_migrations import migrate_schema
from .duckdb_schema import (
    _create_edges_table,
    _create_embedding_cache_table,
    _create_nodes_table,
    _create_session_state_table,
    _create_traversal_cache_table,
    _create_user_actions_table,
    _ensure_sequences,
)

logger = get_logger(__name__)


def initialize_database(
    db_path: Path | None = None, con: duckdb.DuckDBPyConnection | None = None
) -> None:
    """Create all required tables and indexes if they do not exist.

    This function is idempotent: safe to call multiple times. It will not
    drop or modify existing tables. All table and index creations use
    CREATE ... IF NOT EXISTS semantics.

    Args:
        db_path: Path to DuckDB file. Used only if con is None.
            Defaults to data/output/session.duckdb.
        con: Optional existing DuckDB connection. If provided, db_path is ignored
            and the connection is used as-is (caller retains ownership).

    Raises:
        duckdb.Error: If any table creation fails due to syntax or constraint issues.
    """
    close_after = False
    if con is None:
        con = get_connection(db_path)
        close_after = True

    try:
        logger.info("Initializing DuckDB schema")

        _ensure_sequences(con)
        _create_nodes_table(con)
        _create_edges_table(con)
        _create_traversal_cache_table(con)
        _create_session_state_table(con)
        _create_user_actions_table(con)
        _create_embedding_cache_table(con)

        # Record current schema version if not yet set
        from .duckdb_connection import _set_schema_version_if_missing

        _set_schema_version_if_missing(con, SCHEMA_VERSION)

        logger.info("Schema initialization complete")
    finally:
        if close_after and con:
            con.close()


def init_or_migrate(db_path: Path | None = None) -> duckdb.DuckDBPyConnection:
    """Ensure the database exists and is at the latest schema version.

    Convenience entry point for the application: connects to the database,
    runs initialize_database() if needed, and applies any pending migrations.
    Returns an open connection that the caller should eventually close.

    Args:
        db_path: Optional custom database path. Defaults to data/output/session.duckdb.

    Returns:
        An open DuckDB connection ready for use.
    """
    path = db_path or DEFAULT_DB_PATH
    con = get_connection(path)

    try:
        current_version = get_schema_version(db_path=path, con=con)
        target_version = SCHEMA_VERSION

        if current_version < target_version:
            logger.info(
                "Migrating schema",
                extra={"from": current_version, "to": target_version},
            )
            migrate_schema(target_version, db_path=path, con=con)
        else:
            logger.debug(
                "Schema already up-to-date", extra={"version": current_version}
            )

        # Ensure all tables exist even if version tracking is missing
        initialize_database(con=con)

        return con
    except Exception:
        # If migration fails, close connection before re-raising
        con.close()
        raise
