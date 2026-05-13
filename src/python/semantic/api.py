"""Public retrieval API: scoring functions for BM25 index."""

from typing import Dict, List

import numpy as np
from utils.logging import get_logger

from .exceptions import BM25IndexError
from .persistence import load_bm25
from .tokenizer import _TOKENIZER

logger = get_logger(__name__)


def get_scores(query: str) -> Dict[int, float]:
    """Get normalized BM25 relevance scores for all exemplars for a query.

    Scores are min-max normalized to [0, 1]. If all raw scores are equal
    (min == max), returns 0.0 for every exemplar. If the BM25 index is empty
    (no corpus), returns an empty dict.

    Args:
        query: Raw query string; tokenized using configured tokenizer.

    Returns:
        Mapping of exemplar_id → normalized_score in [0, 1].

    Raises:
        BM25IndexError: If index not loaded or scoring fails (except empty).
    """
    data = load_bm25()
    if data is None:
        raise BM25IndexError("BM25 index not loaded")
    bm25 = data["bm25_object"]
    entity_map = data["entity_map"]

    if bm25 is None:
        logger.debug("BM25 index is empty; no scores to return")
        return {}

    tokenized_query = _TOKENIZER(query)
    raw_scores = bm25.get_scores(tokenized_query)  # np.ndarray shape (N,)

    # Normalize to [0, 1]
    min_score = raw_scores.min()
    max_score = raw_scores.max()
    if max_score == min_score:
        normalized = np.zeros_like(raw_scores)
    else:
        normalized = (raw_scores - min_score) / (max_score - min_score)

    # Map corpus index -> exemplar_id
    inverse_map = {idx: eid for eid, idx in entity_map.items()}
    result: Dict[int, float] = {}
    for idx, score in enumerate(normalized):
        exemplar_id = inverse_map.get(idx)
        if exemplar_id is not None:
            result[exemplar_id] = float(score)

    return result


def get_top_n(query: str, n: int = 50) -> List[tuple[int, float]]:
    """Get top-N exemplars by BM25 score for the given query.

    Args:
        query: Raw query string.
        n: Number of top results to return (default 50).

    Returns:
        List of (exemplar_id, score) tuples sorted descending by score.

    Raises:
        BM25IndexError: If index not loaded or scoring fails.
    """
    scores = get_scores(query)
    sorted_items = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    return sorted_items[:n]


def get_index_info() -> Dict[str, object]:
    """Return metadata and basic stats about the loaded index.

    Returns:
        Dict with keys: version, created_at, corpus_hash, tokenizer_config,
        corpus_size, exemplar_count.
    """
    data = load_bm25()
    if data is None:
        raise BM25IndexError("BM25 index not loaded")
    meta = data["metadata"]
    return {
        "version": meta.get("version"),
        "created_at": meta.get("created_at"),
        "corpus_hash": meta.get("corpus_hash"),
        "tokenizer_config": meta.get("tokenizer_config"),
        "corpus_size": len(data["corpus"]),
        "exemplar_count": len(data["entity_map"]),
    }
