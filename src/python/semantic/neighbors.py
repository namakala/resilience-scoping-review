"""k-nearest neighbor discovery by embedding similarity within tag scope.

For a given entity, finds the top-k most similar entities of the same
type within the same ontology subtree. Uses cosine similarity on cached
L2-normalized embeddings (dot product). Results cached in-memory with
5-minute TTL to avoid recomputation during interactive review sessions.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Optional

import duckdb
import numpy as np
from persistence.embedding_cache import get_embedding
from utils.logging import get_logger

from .retrieval.candidates import resolve_candidate_ids

logger = get_logger(__name__)

_MAX_K = 20
_CACHE_TTL = 300  # 5 minutes
_CACHE: dict[
    tuple[int, int],
    tuple[list[tuple[int, float]], float],
] = {}


def _cache_get(
    key: tuple[int, int],
) -> Optional[list[tuple[int, float]]]:
    """Return cached neighbors if within TTL, else None."""
    entry = _CACHE.get(key)
    if entry is not None:
        result, timestamp = entry
        if time.monotonic() - timestamp < _CACHE_TTL:
            return result
        del _CACHE[key]
    return None


def _cache_set(
    key: tuple[int, int],
    value: list[tuple[int, float]],
) -> None:
    """Store neighbors in cache with current timestamp."""
    _CACHE[key] = (value, time.monotonic())


def clear_neighbor_cache() -> None:
    """Clear the in-memory neighbor discovery cache."""
    _CACHE.clear()


def find_neighbors(
    entity_id: int,
    entity_type: str,
    con: duckdb.DuckDBPyConnection,
    k: int = 5,
    model_hash: Optional[str] = None,
    db_path: Optional[Path] = None,
) -> list[tuple[int, float]]:
    """Find k-nearest neighbors by embedding similarity within tag scope.

    Retrieves the entity's ontology tag, resolves all candidates of the
    same type within that tag's subtree, computes cosine similarity
    against each candidate's cached embedding, and returns the top-k
    results with similarity >= 0.5. The query entity is excluded.

    Results are cached in-memory for 300 seconds keyed by
    ``(entity_id, k)``.

    Args:
        entity_id: Query entity ID.
        entity_type: One of ``'exemplar'``, ``'code'``, ``'theme'``,
            or ``'interpretation'``.
        con: Active DuckDB connection for embedding cache and node
            lookups.
        k: Number of neighbors to return. Clamped to [1, 20].
            Default 5.
        model_hash: Optional model version hash for embedding cache
            validity.
        db_path: DuckDB path for scope resolution. Defaults to session
            DB. Currently passed through to ``get_scope_for_tag`` via
            ``resolve_candidate_ids``.

    Returns:
        List of ``(neighbor_id, similarity_score)`` sorted descending
        by score (ties broken by ascending ID). All scores >= 0.5.
        Empty list if no candidates or no embeddings found.

    Raises:
        KeyError: If ``entity_id`` is not found in the ``nodes`` table.
    """
    k = max(1, min(k, _MAX_K))

    cache_key = (entity_id, k)
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    row = con.execute("SELECT tag FROM nodes WHERE id = ?", [entity_id]).fetchone()
    if row is None:
        raise KeyError(f"Node {entity_id} not found")
    tag = str(row[0])

    candidate_ids, _ = resolve_candidate_ids(
        tag,
        entity_type,
        con,
    )
    candidate_ids.discard(entity_id)
    if not candidate_ids:
        return []

    query_emb = get_embedding(
        con,
        str(entity_id),
        entity_type,
        model_hash,
    )
    if query_emb is None:
        logger.warning(
            "No embedding for query entity",
            extra={
                "entity_id": entity_id,
                "entity_type": entity_type,
            },
        )
        return []

    valid_ids: list[int] = []
    embeddings: list[np.ndarray] = []
    for cid in candidate_ids:
        emb = get_embedding(
            con,
            str(cid),
            entity_type,
            model_hash,
        )
        if emb is not None:
            valid_ids.append(cid)
            embeddings.append(emb)

    if not embeddings:
        logger.info(
            "No candidate embeddings found",
            extra={
                "entity_id": entity_id,
                "entity_type": entity_type,
                "candidate_count": len(candidate_ids),
            },
        )
        return []

    matrix = np.stack(embeddings, axis=0)
    similarities: np.ndarray = query_emb @ matrix.T

    scored: list[tuple[int, float]] = [
        (valid_ids[i], float(similarities[i]))
        for i in range(len(valid_ids))
        if similarities[i] >= 0.5
    ]
    scored.sort(key=lambda x: (-x[1], x[0]))
    result = scored[:k]

    _cache_set(cache_key, result)
    return result
