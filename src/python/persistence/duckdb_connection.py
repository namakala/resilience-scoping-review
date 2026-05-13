"""DuckDB connection management and schema version tracking."""

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
