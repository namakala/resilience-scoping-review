"""Batch-encode all exemplar content; store in embedding_cache; immutable.

Loads exemplars from load_exemplars(), determines which need encoding via
cache lookup with content_hash validation, batch-generates embeddings using
generate_embeddings(), and stores results in the embedding_cache DuckDB table.
"""

import time

import duckdb
import polars as pl
from persistence.embedding_cache import put_embedding
from persistence.loaders import load_exemplars
from semantic.embeddings import generate_embeddings, get_model_hash
from tqdm import tqdm
from utils.logging import get_logger

logger = get_logger(__name__)


def generate_exemplar_embeddings(
    con: duckdb.DuckDBPyConnection,
    batch_size: int = 32,
) -> dict:
    """Batch-generate embeddings for all uncached exemplars.

    Loads exemplars via load_exemplars(), queries embedding_cache to find
    which already have valid cached embeddings, and encodes only missing or
    stale (content_hash mismatch) exemplars.

    Args:
        con: Active DuckDB connection for cache queries.
        batch_size: Number of exemplars to encode per model-level batch.

    Returns:
        Dict with keys:
            - total: total exemplars found
            - cached: exemplars already in cache with valid content_hash
            - generated: exemplars newly encoded
            - duration_seconds: total wall-clock time
    """
    start = time.perf_counter()

    exemplars = _collect_exemplars()
    total = len(exemplars)
    if total == 0:
        logger.info("No exemplars to embed")
        return {
            "total": 0,
            "cached": 0,
            "generated": 0,
            "duration_seconds": 0.0,
        }

    model_hash = get_model_hash()

    to_encode = _identify_uncached(con, exemplars, model_hash)
    cached_count = total - len(to_encode)

    generated_count = _encode_and_store(con, to_encode, model_hash, batch_size)

    elapsed = time.perf_counter() - start
    logger.info(
        "Exemplar embedding complete",
        extra={
            "total": total,
            "cached": cached_count,
            "generated": generated_count,
            "duration_seconds": round(elapsed, 2),
        },
    )
    return {
        "total": total,
        "cached": cached_count,
        "generated": generated_count,
        "duration_seconds": round(elapsed, 2),
    }


def _collect_exemplars() -> pl.DataFrame:
    """Load exemplars and collect id, content, content_hash eagerly."""
    lf = load_exemplars().select(["id", "content", "content_hash"])
    return lf.collect()


def _identify_uncached(
    con: duckdb.DuckDBPyConnection,
    exemplars: pl.DataFrame,
    model_hash: str,
) -> list[tuple[str, str, str]]:
    """Return list of (entity_id, content, content_hash) needing encoding.

    Queries embedding_cache for existing exemplar entries matching
    model_hash. Returns only exemplars that are missing or have stale
    content_hash.
    """
    stored = _get_existing_cache_map(con, exemplars, model_hash)

    to_encode: list[tuple[str, str, str]] = []
    for row in exemplars.iter_rows(named=True):
        eid = str(row["id"])
        ch = row["content_hash"]
        if eid in stored and stored[eid] == ch:
            continue
        to_encode.append((eid, row["content"], ch))

    return to_encode


def _get_existing_cache_map(
    con: duckdb.DuckDBPyConnection,
    exemplars: pl.DataFrame,
    model_hash: str,
) -> dict[str, str]:
    """Query embedding_cache for exemplar entries matching model_hash.

    Returns dict mapping entity_id (str) -> stored content_hash.
    """
    ids = [str(eid) for eid in exemplars["id"].to_list()]
    if not ids:
        return {}

    placeholders = ",".join("?" for _ in ids)
    rows = con.execute(
        f"""
        SELECT entity_id, content_hash
        FROM embedding_cache
        WHERE entity_type = 'exemplar'
          AND entity_id IN ({placeholders})
          AND model_hash = ?
        """,
        ids + [model_hash],
    ).fetchall()

    return {row[0]: row[1] for row in rows}


def _encode_and_store(
    con: duckdb.DuckDBPyConnection,
    to_encode: list[tuple[str, str, str]],
    model_hash: str,
    batch_size: int,
) -> int:
    """Batch-encode exemplars and store in cache.

    Returns number of exemplars encoded.
    """
    count = len(to_encode)
    if count == 0:
        return 0

    texts = [item[1] for item in to_encode]

    with tqdm(total=count, desc="Embedding exemplars", unit="ex") as pbar:
        for i in range(0, count, batch_size):
            batch_items = to_encode[i : i + batch_size]  # noqa: E203
            batch_texts = texts[i : i + batch_size]  # noqa: E203

            embeddings = generate_embeddings(batch_texts, batch_size)

            for (eid, _, content_hash), emb in zip(batch_items, embeddings):
                put_embedding(con, eid, "exemplar", emb, model_hash, content_hash)

            pbar.update(len(batch_items))

    return count
