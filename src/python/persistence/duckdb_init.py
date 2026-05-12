from pathlib import Path

import duckdb
from utils.logging import get_logger

logger = get_logger(__name__)

# Default database path (fixed per spec)
DEFAULT_DB_PATH = Path("data/output/session.duckdb")

# Current schema version (bump when migrations are needed)
SCHEMA_VERSION = 1


def get_connection(db_path: Path | None = None) -> duckdb.DuckDBPyConnection:
    """Get a connection to the DuckDB database, creating parent dirs if needed.

    Args:
        db_path: Path to DuckDB file. Defaults to data/output/session.duckdb.

    Returns:
        Active DuckDB connection.

    Raises:
        duckdb.Error: If connection fails (e.g., permission denied, invalid path).
    """
    path = db_path or DEFAULT_DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)

    con = duckdb.connect(str(path))
    # DuckDB v1.5+ includes JSON/parquet; no extensions needed.

    logger.info("Connected to DuckDB", extra={"path": str(path)})
    return con


def _ensure_sequences(con: duckdb.DuckDBPyConnection) -> None:
    """Create sequences used for auto-incrementing primary keys."""
    con.execute("CREATE SEQUENCE IF NOT EXISTS nodes_id_seq START 1;")
    con.execute("CREATE SEQUENCE IF NOT EXISTS ua_seq START 1;")


def _set_schema_version_if_missing(
    con: duckdb.DuckDBPyConnection, version: int
) -> None:
    """Insert schema_version into session_state if key does not yet exist.

    Uses INSERT ... SELECT WHERE NOT EXISTS to avoid overwriting an existing
    (possibly higher) version. Called after table creation to mark DB as
    initialized at the current code's SCHEMA_VERSION.
    """
    con.execute(
        """
        INSERT INTO session_state (key, value, type)
        SELECT ?, CAST(? AS VARCHAR), 'int'
        WHERE NOT EXISTS (
            SELECT 1 FROM session_state WHERE key = ?
        );
    """,
        ["schema_version", str(version), "schema_version"],
    )


def _create_nodes_table(con: duckdb.DuckDBPyConnection) -> None:
    """Create the nodes table if it does not exist."""
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS nodes (
            id INTEGER DEFAULT nextval('nodes_id_seq') PRIMARY KEY,
            type VARCHAR NOT NULL,  -- node type: code/theme/interpretation/tag
            name VARCHAR NOT NULL,
            definition TEXT,
            tag VARCHAR,  -- owning tag; NULL for tag nodes themselves
            status VARCHAR DEFAULT 'active',  -- active/merged/deprecated/rejected
            data_json VARCHAR,  -- extra JSON attributes
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """
    )


def _create_edges_table(con: duckdb.DuckDBPyConnection) -> None:
    """Create the edges table with composite primary key."""
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS edges (
            source_id INTEGER NOT NULL,
            target_id INTEGER NOT NULL,
            edge_type VARCHAR NOT NULL,  -- edge relation
            metadata_json VARCHAR,  -- optional JSON metadata
            PRIMARY KEY (source_id, target_id, edge_type)
        );
    """
    )


def _create_traversal_cache_table(con: duckdb.DuckDBPyConnection) -> None:
    """Create the traversal_cache table for materialized subtree queries."""
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS traversal_cache (
            tag VARCHAR PRIMARY KEY,
            ancestors VARCHAR,  -- JSON array of ancestor tag names
            descendants VARCHAR,  -- JSON array of descendant tag names
            subtree_exemplars VARCHAR,  -- exemplar IDs in subtree
            subtree_codes VARCHAR,  -- code IDs in subtree
            subtree_themes VARCHAR  -- theme IDs in subtree
        );
    """
    )


def _create_session_state_table(con: duckdb.DuckDBPyConnection) -> None:
    """Create the session_state key-value store with type hint column."""
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS session_state (
            key VARCHAR PRIMARY KEY,
            value VARCHAR NOT NULL,  -- JSON-serialized value
            type VARCHAR NOT NULL  -- int, str, dict, list
        );
    """
    )


def _create_user_actions_table(con: duckdb.DuckDBPyConnection) -> None:
    """Create the user_actions audit table with timestamp index."""
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS user_actions (
            action_id INTEGER DEFAULT nextval('ua_seq') PRIMARY KEY,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
            action_type VARCHAR NOT NULL,  -- approve|edit|merge|reject|defer
            entity_id INTEGER NOT NULL,  -- affected node ID
            old_value VARCHAR,  -- JSON snapshot of previous state
            new_value VARCHAR,  -- JSON snapshot of new state
            user_id VARCHAR    -- researcher identifier or session ID
        );
    """
    )
    # Create index on timestamp for audit queries
    try:
        con.execute(
            "CREATE INDEX IF NOT EXISTS "
            "idx_user_actions_timestamp ON user_actions(timestamp);"
        )
    except Exception as e:
        # DuckDB may not support IF NOT EXISTS on CREATE INDEX; log and continue
        logger.warning(
            "Could not create index on user_actions.timestamp", extra={"error": str(e)}
        )


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

        # Record current schema version if not yet set
        _set_schema_version_if_missing(con, SCHEMA_VERSION)

        logger.info("Schema initialization complete")
    finally:
        if close_after and con:
            con.close()


def get_schema_version(
    db_path: Path | None = None, con: duckdb.DuckDBPyConnection | None = None
) -> int:
    """Read the current schema version from session_state.

    Returns:
        Integer schema version (0 if not yet set).

    Args:
        db_path: Path to DuckDB file. Used only if con is None.
        con: Optional existing DuckDB connection.
    """
    close_after = False
    if con is None:
        con = get_connection(db_path)
        close_after = True

    try:
        result = con.execute(
            """
            SELECT value FROM session_state
            WHERE key = 'schema_version' LIMIT 1;
        """
        ).fetchone()

        return int(result[0]) if result else 0
    except Exception as e:
        logger.warning(
            "Could not read schema version; assuming 0", extra={"error": str(e)}
        )
        return 0
    finally:
        if close_after and con:
            con.close()


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
        con.execute(
            """
            INSERT INTO session_state (key, value, type)
            VALUES ('schema_version', '1', 'int')
            ON CONFLICT (key) DO NOTHING;
        """
        )
        logger.info("Applied migration 0→1: initial schema")
    else:
        raise NotImplementedError(
            f"No migration defined from version {from_version} to {to_version}"
        )


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
