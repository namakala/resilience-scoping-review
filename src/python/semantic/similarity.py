"""Cosine similarity matrix between entity embeddings.

Computes pairwise cosine similarity for a set of entity IDs (codes,
themes, etc.) using cached embedding vectors. Embeds from cache are
already L2-normalized, so cosine similarity = dot product.
"""

from __future__ import annotations

from typing import Optional

import duckdb
import numpy as np
from persistence.embedding_cache import get_embedding
from utils.logging import get_logger

from .exceptions import CacheMissError

logger = get_logger(__name__)


def compute_similarity(
    entity_ids: list[int],
    entity_type: str,
    con: duckdb.DuckDBPyConnection,
    model_hash: Optional[str] = None,
) -> np.ndarray:
    """Compute pairwise cosine similarity matrix for entity embeddings.

    Retrieves cached embeddings for each entity ID, stacks into a
    (n, 384) float32 matrix, and computes cosine similarity. Because
    embeddings are already L2-normalized, cosine similarity is returned
    as the dot product matrix. The diagonal is explicitly set to 1.0
    to compensate for numerical drift.

    Args:
        entity_ids: Entity identifiers (integers). Converted to strings
            internally for cache lookup.
        entity_type: Type tag: 'exemplar', 'keyword', 'code', 'theme',
            or 'interpretation'.
        con: Active DuckDB connection for cache queries.
        model_hash: Optional model version hash for cache validity
            checking. If provided, only embeddings matching this hash
            are accepted.

    Returns:
        Float32 numpy array of shape (n, n). Symmetric; diagonal
        entries are exactly 1.0. Values are in [-1, 1] (or [0, 1]
        for non-negative vectors).

    Raises:
        CacheMissError: If any entity_id has no matching embedding in
            the cache (or model_hash mismatch).
    """
    n = len(entity_ids)
    if n == 0:
        return np.zeros((0, 0), dtype="float32")

    embeddings: list[np.ndarray] = []
    for eid in entity_ids:
        emb = get_embedding(con, str(eid), entity_type, model_hash)
        if emb is None:
            raise CacheMissError(f"Embedding not found for {entity_type} id={eid}")
        embeddings.append(emb)

    # Stack into (n, dim) matrix — already float32, already L2-normalized
    matrix = np.stack(embeddings, axis=0)

    # Cosine similarity = dot product because vectors are unit vectors
    sim = matrix @ matrix.T

    # Correct numerical drift on diagonal
    np.fill_diagonal(sim, 1.0)

    return sim
