"""Nodes: embedding model init, exemplar/keyword/code/theme embedding.

Generates embeddings via ``semantic.embeddings.generate_embeddings``
(lazy-loaded singleton model).  Cache payloads are constructed as dicts
for the orchestration layer to persist.
"""

from __future__ import annotations

import numpy as np
import polars as pl
from pipeline.config import Config
from utils.logging import get_logger

logger = get_logger(__name__)

__all__ = [
    "init_embedding_model",
    "embed_exemplars",
    "embed_keywords",
    "embed_codes",
    "embed_themes",
    "cache_exemplar_embeddings",
    "cache_keyword_embeddings",
    "verify_embedding_integrity",
]


def init_embedding_model(config: Config) -> str:
    """Return the embedding model name (triggers lazy load on first use)."""
    return config.embedding_model


def _generate_embeddings(texts: list[str]) -> np.ndarray:
    """Thin wrapper around ``semantic.embeddings.generate_embeddings``."""
    from semantic.embeddings import generate_embeddings as _gen

    return _gen(texts)


def _lf_with_embeddings(lf: pl.LazyFrame, texts_col: str) -> pl.LazyFrame:
    """Add an ``embedding`` column to a LazyFrame by encoding a text column."""
    df = lf.collect()
    texts = df[texts_col].to_list()
    embeddings = _generate_embeddings(texts)
    return df.with_columns(
        pl.Series("embedding", list(embeddings)).alias("embedding")
    ).lazy()


def embed_exemplars(
    load_exemplars: pl.LazyFrame, init_embedding_model: str, config: Config
) -> pl.LazyFrame:
    """Generate exemplar embedding column from exemplar content."""
    return _lf_with_embeddings(load_exemplars, "content")


def embed_keywords(
    load_keywords: pl.LazyFrame, init_embedding_model: str, config: Config
) -> pl.LazyFrame:
    """Generate keyword embedding column from keyword text."""
    return _lf_with_embeddings(load_keywords, "keyword_text")


def embed_codes(
    review_codes: list, init_embedding_model: str, config: Config
) -> pl.LazyFrame:
    """Generate code embedding column from code name + definition."""
    rows = []
    for c in review_codes:
        text = f"{c.get('code_name', '')}: {c.get('definition', '')}"
        rows.append({"id": str(c.get("id", "")), "text": text})
    if not rows:
        return pl.DataFrame(
            schema={"id": pl.String, "embedding": pl.List(pl.Float32)}
        ).lazy()
    texts = [r["text"] for r in rows]
    embeddings = _generate_embeddings(texts)
    data = [{"id": r["id"], "embedding": list(emb)} for r, emb in zip(rows, embeddings)]
    return pl.DataFrame(data).lazy()


def embed_themes(
    review_themes: list, init_embedding_model: str, config: Config
) -> pl.LazyFrame:
    """Generate theme embedding column from theme name + narrative."""
    rows = []
    for t in review_themes:
        text = f"{t.get('theme_name', '')}: {t.get('narrative', '')}"
        rows.append({"id": str(t.get("id", "")), "text": text})
    if not rows:
        return pl.DataFrame(
            schema={"id": pl.String, "embedding": pl.List(pl.Float32)}
        ).lazy()
    texts = [r["text"] for r in rows]
    embeddings = _generate_embeddings(texts)
    data = [{"id": r["id"], "embedding": list(emb)} for r, emb in zip(rows, embeddings)]
    return pl.DataFrame(data).lazy()


def cache_exemplar_embeddings(embed_exemplars: pl.LazyFrame, config: Config) -> dict:
    """Build a cache payload dict for exemplar embeddings."""
    df = embed_exemplars.collect()
    return {
        "entity_type": "exemplar",
        "count": df.height,
        "entries": df.select(["id", "embedding"]).to_dict(as_series=False),
    }


def cache_keyword_embeddings(embed_keywords: pl.LazyFrame, config: Config) -> dict:
    """Build a cache payload dict for keyword embeddings."""
    df = embed_keywords.collect()
    return {
        "entity_type": "keyword",
        "count": df.height,
        "entries": df.select(["keyword_id", "embedding"]).to_dict(as_series=False),
    }


def verify_embedding_integrity(
    embed_exemplars: pl.LazyFrame,
    embed_keywords: pl.LazyFrame,
    config: Config,
) -> dict:
    """Verify all embeddings are 384-dim float32 with no NaN."""
    from semantic.embeddings import EMBEDDING_DIM

    results = {}
    for name, lf in [("exemplars", embed_exemplars), ("keywords", embed_keywords)]:
        embeddings = lf.collect()["embedding"].to_list()
        if not embeddings:
            results[name] = {"count": 0, "valid": True}
            continue
        emb_array = np.array(embeddings, dtype=np.float32)
        results[name] = {
            "count": len(embeddings),
            "shape": emb_array.shape,
            "dim_ok": emb_array.shape[-1] == EMBEDDING_DIM,
            "has_nan": bool(np.isnan(emb_array).any()),
        }
    return results
