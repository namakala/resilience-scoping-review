"""Weight configuration for hybrid retrieval rerank step.

Two weight presets:

- Exemplar:  ``emb=0.5  prox=0.3  bm25=0.2``
- Non-exemplar: ``emb=0.625 prox=0.375 bm25=0.0`` (renormalized after
  dropping the BM25 term)
"""

from __future__ import annotations

from typing import NamedTuple


class WeightConfig(NamedTuple):
    """Weight triplet for hybrid retrieval rerank (emb, prox, bm25)."""

    emb: float
    prox: float
    bm25: float


_W_EXEMPLAR = WeightConfig(0.5, 0.3, 0.2)
_W_NON_EXEMPLAR = WeightConfig(0.625, 0.375, 0.0)

_WEIGHT_MAP: dict[str, WeightConfig] = {
    "exemplar": _W_EXEMPLAR,
    "non_exemplar": _W_NON_EXEMPLAR,
}


def select_weights(candidate_type: str) -> WeightConfig:
    """Return the appropriate WeightConfig for a candidate type.

    Args:
        candidate_type: ``'exemplar'`` for BM25-weighted config;
            any other value returns the renormalized non-exemplar
            config.

    Returns:
        ``WeightConfig`` with ``emb``, ``prox``, ``bm25`` fields.
    """
    return _WEIGHT_MAP.get(candidate_type, _W_NON_EXEMPLAR)
