"""DuckDB table schemas and DDL definitions."""

import duckdb
from utils.logging import get_logger

logger = get_logger(__name__)


def _ensure_sequences(con: duckdb.DuckDBPyConnection) -> None:
    """Create sequences used for auto-incrementing primary keys."""
    con.execute("CREATE SEQUENCE IF NOT EXISTS nodes_id_seq START 1;")
    con.execute("CREATE SEQUENCE IF NOT EXISTS ua_seq START 1;")


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
            subtree_themes VARCHAR,  -- theme IDs in subtree
            stale BOOLEAN DEFAULT FALSE  -- invalidated; needs recompute
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


def _create_embedding_cache_table(con: duckdb.DuckDBPyConnection) -> None:
    """Create the embedding_cache table for cached embeddings
    with content-hash invalidation."""
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS embedding_cache (
            entity_id VARCHAR NOT NULL,
            entity_type VARCHAR NOT NULL,  -- exemplar|keyword|code|theme|interpretation
            embedding BLOB NOT NULL,  -- serialized float32 array
            model_hash VARCHAR NOT NULL,
            content_hash VARCHAR NOT NULL,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (entity_id, entity_type)
        );
    """
    )
    # Create index on content_hash for cache invalidation scans (non-unique)
    try:
        con.execute(
            "CREATE INDEX IF NOT EXISTS "
            "idx_embedding_cache_content_hash ON embedding_cache(content_hash);"
        )
    except Exception as e:
        logger.warning(
            "Could not create index on embedding_cache.content_hash",
            extra={"error": str(e)},
        )
