"""Corpus construction from keyword parquet.

Builds tokenized corpus and exemplar_id→index map. Pure functions operating
on the keyword corpus.
"""

from typing import Dict, List

import polars as pl
from utils.logging import get_logger

logger = get_logger(__name__)


def _load_keywords_lazy() -> pl.LazyFrame:
    """Lazy-load keywords.parquet using persistence loader.

    Returns:
        LazyFrame with schema: keyword_id, exemplar_id, keyword_text, frequency.
    """
    from persistence.loaders import load_keywords  # deferred import to avoid cycles

    return load_keywords()


def _build_corpus_and_map() -> tuple[List[List[str]], Dict[int, int]]:
    """Construct tokenized corpus and exemplar_id→index map from keywords.

    Groups keywords by exemplar_id (ascending order), sorts keywords
    alphabetically within each exemplar, tokenizes via configured tokenizer.

    Returns:
        corpus: List of token lists, order = sorted exemplar_id ascending.
        entity_map: Dict mapping exemplar_id → corpus index.
    """
    lf = _load_keywords_lazy()
    df = lf.select(["exemplar_id", "keyword_text"]).collect()

    if df.height == 0:
        logger.warning("Keywords corpus is empty; building empty BM25 index")
        return [], {}

    # Group keywords by exemplar_id
    grouped = (
        df.group_by("exemplar_id")
        .agg(pl.col("keyword_text").sort())
        .sort("exemplar_id")
    )

    corpus: List[List[str]] = []
    entity_map: Dict[int, int] = {}

    for idx, row in enumerate(grouped.iter_rows()):
        exemplar_id = row[0]  # exemplar_id
        keyword_list = row[1]  # List[str] (already sorted)
        # Import tokenizer at module level would create cycle; call lazily
        from .tokenizer import _TOKENIZER

        tokenized = _TOKENIZER(
            " ".join(keyword_list)
        )  # join then retokenize with pipeline
        corpus.append(tokenized)
        entity_map[exemplar_id] = idx

    logger.info(
        "Corpus built",
        extra={"documents": len(corpus), "vocab_exemplars": len(entity_map)},
    )
    return corpus, entity_map


def _compute_corpus_hash(corpus: List[List[str]]) -> str:
    """Compute deterministic SHA256 hash of the corpus for rebuild detection.

    Strategy: for each exemplar's sorted keywords, join with ':' -> concatenate
    all exemplar strings with '|' using exemplar_id ascending order.

    Args:
        corpus: List of token lists (deterministic order).

    Returns:
        First 16 hex characters of SHA256 digest.
    """
    import hashlib

    if not corpus:
        return hashlib.sha256(b"<empty>").hexdigest()[:16]

    # Reconstruct per-exemplar sorted keyword strings
    parts = []
    for doc in corpus:
        # Sort tokens alphabetically for hash stability
        sorted_tokens = sorted(doc)
        parts.append(":".join(sorted_tokens))
    joined = "|".join(parts)
    return hashlib.sha256(joined.encode()).hexdigest()[:16]
