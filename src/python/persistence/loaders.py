"""Lazy-loading functions for immutable artifacts from Parquet.

Provides cached access to exemplars, tags, and keywords with
on-the-fly computed columns: content_hash (recomputed defensively),
keyword_count, tag parent/depth derivation.
"""

import hashlib
from functools import lru_cache
from pathlib import Path

import polars as pl
from utils.logging import get_logger

# Paths (configurable for testing, default to project layout)
EXEMPLARS_PARQUET = Path("data/processed/exemplars.parquet")
TAGS_PARQUET = Path("data/processed/tags.parquet")
KEYWORDS_PARQUET = Path("data/processed/keywords.parquet")

logger = get_logger(__name__)


def _recompute_content_hash(content_col: pl.Expr) -> pl.Expr:
    """Defensively recompute SHA256(content)[:16] as hex string."""
    return (
        content_col.cast(pl.String).map_elements(
            lambda c: hashlib.sha256(c.encode()).hexdigest()[:16],
            return_dtype=pl.String,
        )
    ).alias("content_hash")


@lru_cache(maxsize=1)
def load_exemplars() -> pl.LazyFrame:
    """Lazy-load exemplars from Parquet with recomputed content_hash and keyword_count.

    Reads from data/processed/exemplars.parquet. Always recomputes content_hash
    from the content column (defensive integrity check). Adds keyword_count as
    the length of the keywords list.

    Returns:
        Polars LazyFrame with schema:
            id: Int64
            document: String
            tag: Categorical
            content: String
            keywords: List(String)
            content_hash: String  (recomputed)
            keyword_count: Int64

    Note:
        Result is cached in memory after first call. Subsequent calls return
        the same LazyFrame instance (deferred computation preserved).
    """
    logger.info("Loading exemplars (cached)", extra={"path": str(EXEMPLARS_PARQUET)})

    if not EXEMPLARS_PARQUET.exists():
        raise FileNotFoundError(f"Exemplars Parquet not found: {EXEMPLARS_PARQUET}")

    lf = pl.scan_parquet(EXEMPLARS_PARQUET)

    # Drop any existing content_hash to ensure defensive recompute
    if "content_hash" in lf.collect_schema().names():
        lf = lf.drop("content_hash")

    enriched = lf.with_columns(
        [
            _recompute_content_hash(pl.col("content")),
            pl.col("keywords").list.len().cast(pl.Int64).alias("keyword_count"),
        ]
    )

    return enriched


@lru_cache(maxsize=1)
def load_tags() -> pl.LazyFrame:
    """Lazy-load tags from Parquet with derived parent and depth.

    Reads from data/processed/tags.parquet. Derives 'parent' by splitting
    the tag string on '.' (ancestor portion) and 'depth' by counting
    separators + 1 (root tags have depth=1, parent="").

    Returns:
        Polars LazyFrame with schema:
            tag: Categorical
            parent: String
            description: String
            depth: Int64

    Note:
        Result is cached in memory after first call.
    """
    logger.info("Loading tags (cached)", extra={"path": str(TAGS_PARQUET)})

    if not TAGS_PARQUET.exists():
        raise FileNotFoundError(f"Tags Parquet not found: {TAGS_PARQUET}")

    lf = pl.scan_parquet(TAGS_PARQUET)

    # Derive parent and depth from tag string
    # "Problem.Cause.Impact" -> parent="Problem.Cause", depth=3
    tag_str = pl.col("tag").cast(pl.String)
    parts = tag_str.str.split(".")
    parent = (
        parts.list.slice(0, parts.list.len() - 1)
        .list.join(".")
        .fill_null("")
        .alias("parent")
    )
    depth = parts.list.len().cast(pl.Int64).alias("depth")

    enriched = lf.with_columns(
        [
            parent,
            depth,
        ]
    )

    # Keep only required columns per spec: tag, parent, description, depth
    # Drop n_contents and any other artifacts
    result = enriched.select(["tag", "parent", "description", "depth"])

    return result


@lru_cache(maxsize=1)
def load_keywords() -> pl.LazyFrame:
    """Lazy-load keywords from Parquet; return empty LazyFrame if absent.

    Reads from data/processed/keywords.parquet. If the file does not exist
    (keywords not yet extracted), returns an empty LazyFrame with the correct
    schema to allow downstream code to type-check safely.

    Returns:
        Polars LazyFrame with schema:
            keyword_id: Int64
            exemplar_id: Int64
            keyword_text: String
            frequency: Int32

    Note:
        Result is cached in memory after first call.
    """
    logger.info("Loading keywords (cached)", extra={"path": str(KEYWORDS_PARQUET)})

    if KEYWORDS_PARQUET.exists():
        lf = pl.scan_parquet(KEYWORDS_PARQUET)
        logger.info(
            "Keywords loaded", extra={"rows": lf.select(pl.len()).collect().item()}
        )
        return lf
    else:
        logger.warning("Keywords Parquet not found; returning empty LazyFrame")
        empty_df = pl.DataFrame(
            schema={
                "keyword_id": pl.Int64,
                "exemplar_id": pl.Int64,
                "keyword_text": pl.String,
                "frequency": pl.Int32,
            }
        )
        return empty_df.lazy()


def clear_cache() -> None:
    """Clear in-memory caches for all loaders (useful for tests)."""
    load_exemplars.cache_clear()
    load_tags.cache_clear()
    load_keywords.cache_clear()
    logger.info("Loader caches cleared")


__all__ = [
    "load_exemplars",
    "load_tags",
    "load_keywords",
    "clear_cache",
]
