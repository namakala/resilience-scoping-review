"""Batch-encode keyword strings into embedding_cache; immutable.

Reads keywords.parquet via load_keywords(), encodes each keyword string
individually as entity_type='keyword'. Uses shared helpers from
embedding_generation for cache lookup and batch encoding.
"""

import hashlib
import time

import duckdb
from persistence.loaders import load_keywords
from semantic.embedding_generation import (
    _encode_and_store_generic,
    _get_existing_cache_map_generic,
    _identify_uncached,
)
from semantic.embeddings import get_model_hash
from utils.logging import get_logger

logger = get_logger(__name__)


def generate_keyword_embeddings(
    con: duckdb.DuckDBPyConnection,
    batch_size: int = 32,
) -> dict:
    """Batch-generate embeddings for all uncached keywords.

    Reads keywords from keywords.parquet via load_keywords(), queries
    embedding_cache to find which already have valid cached embeddings,
    and encodes only missing or stale (content_hash mismatch) keywords.

    Args:
        con: Active DuckDB connection for cache queries.
        batch_size: Number of keywords to encode per model-level batch.

    Returns:
        Dict: total (keyword rows), cached, generated, duration_seconds.
    """
    start = time.perf_counter()

    kw_items = _collect_keyword_items()
    total = len(kw_items)
    if total == 0:
        logger.info("No keywords to embed")
        return {
            "total": 0,
            "cached": 0,
            "generated": 0,
            "duration_seconds": 0.0,
        }

    model_hash = get_model_hash()

    to_encode = _identify_uncached_keywords(con, kw_items, model_hash)
    cached_count = total - len(to_encode)

    generated_count = _encode_and_store_keywords(con, to_encode, model_hash, batch_size)

    elapsed = time.perf_counter() - start
    logger.info(
        "Keyword embedding complete",
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


def _collect_keyword_items() -> list[tuple[str, str, str]]:
    """Load keywords and build list of (entity_id, text, content_hash).

    Groups by exemplar_id, sorts by frequency descending, and assigns
    positional index for entity_id construction.
    """
    kw_lf = load_keywords()
    df = kw_lf.collect()
    if df.height == 0:
        return []

    sorted_kw = df.sort(["exemplar_id", "frequency"], descending=[False, True])

    items: list[tuple[str, str, str]] = []
    current_eid: int | None = None
    idx = 0

    for row in sorted_kw.iter_rows(named=True):
        eid = row["exemplar_id"]
        if eid != current_eid:
            current_eid = eid
            idx = 0
        kw_text = row["keyword_text"]
        ch = hashlib.sha256(kw_text.encode()).hexdigest()[:16]
        entity_id = f"{eid}_kw_{idx}"
        items.append((entity_id, kw_text, ch))
        idx += 1

    return items


def _identify_uncached_keywords(
    con: duckdb.DuckDBPyConnection,
    kw_items: list[tuple[str, str, str]],
    model_hash: str,
) -> list[tuple[str, str, str]]:
    """Return list of (entity_id, text, content_hash) needing encoding."""
    ids = [item[0] for item in kw_items]
    stored = _get_existing_cache_map_generic(con, ids, "keyword", model_hash)
    return _identify_uncached(kw_items, stored)


def _encode_and_store_keywords(
    con: duckdb.DuckDBPyConnection,
    to_encode: list[tuple[str, str, str]],
    model_hash: str,
    batch_size: int,
) -> int:
    """Batch-encode keywords and store in cache.

    Returns number of keywords encoded.
    """
    return _encode_and_store_generic(
        con,
        to_encode,
        "keyword",
        model_hash,
        batch_size,
        desc="Embedding keywords",
        unit="kw",
    )
