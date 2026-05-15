"""Pure BM25 scoring functions.

Every function accepts an already-built BM25 index dict as a parameter —
no file I/O, no global state.  Suitable for use in both the Hamilton DAG
and the orchestration layer.
"""

from __future__ import annotations

from typing import Callable  # noqa: F401

import numpy as np
from utils.logging import get_logger

from .tokenizer import _TOKENIZER

logger = get_logger(__name__)

__all__ = ["get_scores", "get_top_n", "get_index_info"]


def _normalize_scores(raw: np.ndarray) -> np.ndarray:
    """Min-max normalize a 1-D array to [0, 1].

    If all values are equal, returns a zero array of the same shape.
    """
    mn, mx = raw.min(), raw.max()
    if mx == mn:
        return np.zeros_like(raw)
    return (raw - mn) / (mx - mn)


def get_scores(
    query: str,
    bm25_index: dict,
    tokenizer: Callable[[str], list[str]] | None = None,
) -> dict[int, float]:
    """BM25 relevance scores for all exemplars, normalized to [0, 1].

    Parameters
    ----------
    query :
        Raw query string (tokenized internally).
    bm25_index :
        Index dict as returned by :func:`build_index`.
    tokenizer :
        Tokenizer callable.  Defaults to the module-level singleton.

    Returns
    -------
    dict
        Mapping of ``exemplar_id`` → score in [0, 1].
    """
    bm25 = bm25_index["bm25_object"]
    entity_map = bm25_index["entity_map"]

    if bm25 is None:
        logger.debug("BM25 index is empty; no scores to return")
        return {}

    tok = tokenizer or _TOKENIZER
    tokenized_query = tok(query)
    raw_scores: np.ndarray = bm25.get_scores(tokenized_query)
    normalized = _normalize_scores(raw_scores)

    inverse_map = {idx: eid for eid, idx in entity_map.items()}
    return {
        inverse_map[idx]: float(score)
        for idx, score in enumerate(normalized)
        if idx in inverse_map
    }


def get_top_n(
    query: str,
    bm25_index: dict,
    n: int = 50,
) -> list[tuple[int, float]]:
    """Top-N exemplars by BM25 score, sorted descending.

    Parameters
    ----------
    query :
        Raw query string.
    bm25_index :
        Index dict as returned by :func:`build_index`.
    n :
        Maximum results to return (default 50).

    Returns
    -------
    list[tuple[int, float]]
        ``(exemplar_id, score)`` tuples sorted descending by score.
    """
    scores = get_scores(query, bm25_index)
    return sorted(scores.items(), key=lambda kv: kv[1], reverse=True)[:n]


def get_index_info(bm25_index: dict) -> dict:
    """Metadata and basic stats about a BM25 index.

    Parameters
    ----------
    bm25_index :
        Index dict as returned by :func:`build_index`.

    Returns
    -------
    dict
        Keys: ``corpus_size``, ``exemplar_count``, ``tokenizer_config``,
        ``corpus_hash``.
    """
    meta = bm25_index["metadata"]
    return {
        "corpus_size": meta["corpus_size"],
        "exemplar_count": meta["exemplar_count"],
        "tokenizer_config": meta["tokenizer_config"],
        "corpus_hash": meta["corpus_hash"],
    }
