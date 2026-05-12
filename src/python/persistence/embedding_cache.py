"""CRUD operations for embedding cache with content-hash invalidation.

Provides get/put/invalidate operations for cached embeddings stored in DuckDB.
Serializes NumPy float32 arrays as BLOBs. Cache keyed by (entity_id, entity_type).
Lookup respects model_hash and content_hash for validity.
"""

from typing import Optional

import duckdb
import numpy as np
from utils.logging import get_logger

logger = get_logger(__name__)


def get_embedding(
    con: duckdb.DuckDBPyConnection,
    entity_id: str,
    entity_type: str,
    model_hash: Optional[str] = None,
) -> Optional[np.ndarray]:
    """Retrieve a cached embedding for an entity.

    Queries embedding_cache by (entity_id, entity_type). If model_hash is
    provided and the stored model_hash differs, returns None (cache miss/mismatch).
    Deserializes the BLOB to a float32 NumPy array.

    Args:
        con: Active DuckDB connection.
        entity_id: Unique identifier of the entity (string).
        entity_type: Type tag: 'exemplar', 'keyword', 'code', 'theme',
        or 'interpretation'.
        model_hash: Optional hash of the embedding model version. If provided,
            the stored model_hash must match or None is returned.

    Returns:
        Deserialized NumPy float32 array if cache hit; None if missing or model
        hash mismatch.
    """
    try:
        row = con.execute(
            """
            SELECT embedding, model_hash
            FROM embedding_cache
            WHERE entity_id = ? AND entity_type = ?
            """,
            [entity_id, entity_type],
        ).fetchone()

        if row is None:
            logger.debug(
                "Cache miss: embedding not found",
                extra={"entity_id": entity_id, "entity_type": entity_type},
            )
            return None

        blob, stored_model_hash = row

        if model_hash is not None and stored_model_hash != model_hash:
            logger.debug(
                "Cache miss: model hash mismatch",
                extra={
                    "entity_id": entity_id,
                    "entity_type": entity_type,
                    "expected": model_hash,
                    "found": stored_model_hash,
                },
            )
            return None

        # Deserialize BLOB to NumPy array
        arr = np.frombuffer(blob, dtype="float32").copy()
        logger.debug(
            "Cache hit",
            extra={
                "entity_id": entity_id,
                "entity_type": entity_type,
                "dim": arr.shape[0],
            },
        )
        return arr
    except Exception as e:
        logger.error(
            "Failed to retrieve embedding from cache",
            extra={"error": str(e), "entity_id": entity_id, "entity_type": entity_type},
        )
        raise


def put_embedding(
    con: duckdb.DuckDBPyConnection,
    entity_id: str,
    entity_type: str,
    embedding: np.ndarray,
    model_hash: str,
    content_hash: str,
) -> None:
    """Insert or update an embedding in the cache (upsert).

    Serializes the embedding as a float32 BLOB and inserts or updates the
    cache row. On conflict (same entity_id + entity_type), replaces the embedding,
    model_hash, and content_hash. The timestamp column defaults to CURRENT_TIMESTAMP
    on insert; updates do not modify timestamp (the original insert time is retained).

    Args:
        con: Active DuckDB connection.
        entity_id: Unique identifier of the entity (string).
        entity_type: Type tag: 'exemplar'|'keyword'|'code'|'theme'|'interpretation'.
        embedding: NumPy array (float32). Will be cast to float32 if not already.
        model_hash: Hash of the embedding model used (from compute_model_hash).
        content_hash: Hash of the entity's content for invalidation scans.
    """
    try:
        # Ensure float32 and serialize
        arr = np.asarray(embedding, dtype="float32")
        blob = arr.tobytes()

        con.execute(
            """
            INSERT INTO embedding_cache
                (entity_id, entity_type, embedding, model_hash, content_hash)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT (entity_id, entity_type) DO UPDATE SET
                embedding = excluded.embedding,
                model_hash = excluded.model_hash,
                content_hash = excluded.content_hash;
            """,
            [entity_id, entity_type, blob, model_hash, content_hash],
        )
        logger.debug(
            "Embedding cached",
            extra={
                "entity_id": entity_id,
                "entity_type": entity_type,
                "dim": arr.shape[0],
                "model_hash": model_hash,
            },
        )
    except Exception as e:
        logger.error(
            "Failed to write embedding to cache",
            extra={"error": str(e), "entity_id": entity_id, "entity_type": entity_type},
        )
        raise


def invalidate_entity(
    con: duckdb.DuckDBPyConnection, entity_id: str, entity_type: str
) -> int:
    """Remove cached embedding for an entity.

    Called when the entity's content changes or the embedding model is updated.
    Deletes the row identified by (entity_id, entity_type).

    Args:
        con: Active DuckDB connection.
        entity_id: Entity identifier to invalidate.
        entity_type: Entity type tag.

    Returns:
        Number of rows deleted (0 or 1).
    """
    try:
        rows = con.execute(
            "DELETE FROM embedding_cache WHERE entity_id = ? "
            "AND entity_type = ? RETURNING *",
            [entity_id, entity_type],
        ).fetchall()
        rowcount = len(rows)
        if rowcount > 0:
            logger.debug(
                "Cache invalidated",
                extra={"entity_id": entity_id, "entity_type": entity_type},
            )
        return rowcount
    except Exception as e:
        logger.error(
            "Failed to invalidate embedding cache",
            extra={"error": str(e), "entity_id": entity_id, "entity_type": entity_type},
        )
        raise


def invalidate_by_content_hash(
    con: duckdb.DuckDBPyConnection, content_hash: str
) -> int:
    """Remove all cache entries that match a given content_hash.

    Useful for bulk invalidation when a source artifact (e.g., a file) changes
    and all derived embeddings must be regenerated.

    Args:
        con: Active DuckDB connection.
        content_hash: Hash of the content to invalidate.

    Returns:
        Number of rows deleted.
    """
    try:
        rows = con.execute(
            "DELETE FROM embedding_cache WHERE content_hash = ? RETURNING *",
            [content_hash],
        ).fetchall()
        rowcount = len(rows)
        logger.debug(
            "Bulk cache invalidation",
            extra={"content_hash": content_hash, "deleted": rowcount},
        )
        return rowcount
    except Exception as e:
        logger.error(
            "Failed to invalidate cache by content_hash",
            extra={"error": str(e), "content_hash": content_hash},
        )
        raise
