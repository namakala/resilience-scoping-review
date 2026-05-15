"""BM25 index builder — constructs a lexical index from keyword data.

Pure function — no file I/O, no cache mutation.  Returns the BM25 index
as a dict so callers can persist it if they wish.
"""

from __future__ import annotations

import polars as pl
from utils.logging import get_logger

from .corpus import build_corpus_from_keywords, compute_corpus_hash
from .tokenizer import _build_tokenizer, _parse_tokenizer_config

logger = get_logger(__name__)

__all__ = ["build_index"]


def build_index(
    keywords_lf: pl.LazyFrame,
    tokenizer_config: str = "lowercase,split_by_space",
) -> dict:
    """Build a BM25 index dict from in-memory keyword data.

    Parameters
    ----------
    keywords_lf :
        Keyword data with columns ``exemplar_id``, ``keyword_text``.
    tokenizer_config :
        Comma-separated tokenizer toggles (default
        ``"lowercase,split_by_space"``).

    Returns
    -------
    dict
        Keys: ``bm25_object`` (:class:`BM25Okapi` or ``None``),
        ``corpus`` (list of token lists), ``entity_map``
        (exemplar_id → corpus index), ``metadata`` (dict with
        ``corpus_size``, ``exemplar_count``, ``tokenizer_config``,
        ``corpus_hash``).
    """
    toggles = _parse_tokenizer_config(tokenizer_config)
    tokenizer = _build_tokenizer(toggles)

    corpus, entity_map = build_corpus_from_keywords(keywords_lf, tokenizer)
    corpus_hash = compute_corpus_hash(corpus)

    from rank_bm25 import BM25Okapi

    bm25 = BM25Okapi(corpus) if corpus else None

    logger.info(
        "BM25 index built",
        extra={
            "docs": len(corpus),
            "exemplars": len(entity_map),
            "tokenizer_config": tokenizer_config,
        },
    )

    return {
        "bm25_object": bm25,
        "corpus": corpus,
        "entity_map": entity_map,
        "metadata": {
            "corpus_size": len(corpus),
            "exemplar_count": len(entity_map),
            "tokenizer_config": tokenizer_config,
            "corpus_hash": corpus_hash,
        },
    }
