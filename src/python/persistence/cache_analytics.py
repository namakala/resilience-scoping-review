"""Cache analytics and monitoring for embedding cache.

Provides statistical queries and health metrics for the embedding cache.
Separated from CRUD operations to respect query-command separation.
"""

import duckdb
from utils.logging import get_logger

logger = get_logger(__name__)


def get_cache_stats(con: duckdb.DuckDBPyConnection) -> dict:
    """Return aggregate statistics about the embedding cache.

    Stats include total rows, breakdown by entity_type, and cache hit-rate
    approximations (requires external tracking of requests; here returns only
    stored counts).

    Args:
        con: Active DuckDB connection.

    Returns:
        Dictionary with keys: total, by_entity_type (dict), oldest, newest.
    """
    try:
        total = con.execute("SELECT COUNT(*) FROM embedding_cache").fetchone()[0]
        by_type_rows = con.execute(
            "SELECT entity_type, COUNT(*) FROM embedding_cache GROUP BY entity_type"
        ).fetchall()
        by_type = {row[0]: row[1] for row in by_type_rows}
        bounds = con.execute(
            "SELECT MIN(timestamp), MAX(timestamp) FROM embedding_cache"
        ).fetchone()
        return {
            "total": total,
            "by_entity_type": by_type,
            "oldest": bounds[0],
            "newest": bounds[1],
        }
    except Exception as e:
        logger.error("Failed to query cache stats", extra={"error": str(e)})
        raise
