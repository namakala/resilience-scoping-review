"""Corpus construction from keyword data.

Pure functions that build a tokenized corpus and exemplar_id-to-index map
from in-memory keyword data.  No file I/O — callers pass keyword data and
a tokenizer callable.
"""

from __future__ import annotations

import hashlib
from typing import Callable

import polars as pl
from utils.logging import get_logger

logger = get_logger(__name__)

__all__ = [
    "build_corpus_from_keywords",
    "compute_corpus_hash",
]


def build_corpus_from_keywords(
    keywords_lf: pl.LazyFrame,
    tokenizer: Callable[[str], list[str]],
    exemplar_content_map: dict[int, str] | None = None,
) -> tuple[list[list[str]], dict[int, int]]:
    """Construct tokenized corpus and exemplar_id→index map.

    Groups keyword rows by exemplar_id (ascending), sorts keywords
    alphabetically within each exemplar, then tokenizes via the provided
    callable.  When *exemplar_content_map* is provided, each exemplar's
    content text is appended to its keyword tokens before tokenizing,
    enriching the BM25 index with full-content lexical signal.

    Parameters
    ----------
    keywords_lf :
        LazyFrame with columns ``exemplar_id``, ``keyword_text`` (and
        optionally others — only those two are used).
    tokenizer :
        Callable that accepts a raw string and returns a list of tokens.
    exemplar_content_map :
        Optional dict mapping exemplar_id → content text.  When provided,
        the content is appended to the keyword string before tokenization.

    Returns
    -------
    corpus :
        List of token lists in exemplar_id ascending order.
    entity_map :
        Dict mapping exemplar_id → corpus index.
    """
    df = keywords_lf.select(["exemplar_id", "keyword_text"]).collect()

    if df.height == 0:
        logger.warning("Keywords corpus is empty; returning empty corpus")
        return [], {}

    grouped = (
        df.group_by("exemplar_id")
        .agg(pl.col("keyword_text").sort())
        .sort("exemplar_id")
    )

    corpus: list[list[str]] = []
    entity_map: dict[int, int] = {}

    for idx, row in enumerate(grouped.iter_rows()):
        exemplar_id = row[0]
        keyword_list: list[str] = row[1]
        text = " ".join(keyword_list)
        if exemplar_content_map and exemplar_id in exemplar_content_map:
            text += " " + exemplar_content_map[exemplar_id]
        tokenized = tokenizer(text)
        corpus.append(tokenized)
        entity_map[exemplar_id] = idx

    logger.info(
        "Corpus built",
        extra={"documents": len(corpus), "vocab_exemplars": len(entity_map)},
    )
    return corpus, entity_map


def compute_corpus_hash(corpus: list[list[str]]) -> str:
    """Deterministic SHA256 hash of the corpus for rebuild detection.

    For each exemplar's sorted keyword tokens, joins with ``:``, then
    concatenates all exemplar strings with ``|`` in ascending order.
    Returns the first 16 hex characters of the digest.

    Parameters
    ----------
    corpus :
        List of token lists in deterministic order.

    Returns
    -------
    str
        16-character hex hash.
    """
    if not corpus:
        return hashlib.sha256(b"<empty>").hexdigest()[:16]

    parts = []
    for doc in corpus:
        sorted_tokens = sorted(doc)
        parts.append(":".join(sorted_tokens))
    joined = "|".join(parts)
    return hashlib.sha256(joined.encode()).hexdigest()[:16]
