"""Cosine similarity matrix between entity embeddings.

Computes pairwise cosine similarity for a set of entity IDs (codes,
themes, etc.) using cached embedding vectors. Embeds from cache are
already L2-normalized, so cosine similarity = dot product.
"""

from __future__ import annotations

from typing import Callable, List, Optional

import duckdb
import numpy as np
from persistence.embedding_cache import get_embedding
from utils.logging import get_logger

from .embeddings import generate_embedding
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


def compute_theme_hybrid_similarity(
    name_a: str,
    narrative_a: str,
    exemplar_ids_a: List[int],
    name_b: str,
    narrative_b: str,
    exemplar_ids_b: List[int],
    con: duckdb.DuckDBPyConnection,
) -> float:
    """Compute hybrid similarity between two themes.

    Averages three components:

    1. **Name cosine** — on-the-fly embedding of each theme's name.
    2. **Narrative cosine** — on-the-fly embedding of each theme's
       narrative.
    3. **Exemplar pairwise cosine** — average of max-pooled cross-pair
       cosine from cached exemplar embeddings.

    All embeddings are L2-normalised, so cosine = dot product.

    Returns a float in ``[0, 1]``.  Returns 0.0 if both theme names are
    empty or no exemplar embeddings are found.
    """
    name_emb_a = generate_embedding(name_a) if name_a else None
    name_emb_b = generate_embedding(name_b) if name_b else None
    narr_emb_a = generate_embedding(narrative_a) if narrative_a else None
    narr_emb_b = generate_embedding(narrative_b) if narrative_b else None

    components: list[float] = []

    if name_emb_a is not None and name_emb_b is not None:
        components.append(float(name_emb_a @ name_emb_b))
    if narr_emb_a is not None and narr_emb_b is not None:
        components.append(float(narr_emb_a @ narr_emb_b))

    # Exemplar pairwise similarity
    ex_embs_a: list[np.ndarray] = []
    for eid in exemplar_ids_a:
        emb = get_embedding(con, str(eid), "exemplar")
        if emb is not None:
            ex_embs_a.append(emb)

    ex_embs_b: list[np.ndarray] = []
    for eid in exemplar_ids_b:
        emb = get_embedding(con, str(eid), "exemplar")
        if emb is not None:
            ex_embs_b.append(emb)

    if ex_embs_a and ex_embs_b:
        matrix_a = np.stack(ex_embs_a, axis=0)  # (n_a, 384)
        matrix_b = np.stack(ex_embs_b, axis=0)  # (n_b, 384)
        cross = matrix_a @ matrix_b.T  # (n_a, n_b)
        sim_a = float(cross.max(axis=1).mean())  # avg best match for each A
        sim_b = float(cross.max(axis=0).mean())  # avg best match for each B
        components.append(0.5 * sim_a + 0.5 * sim_b)

    if not components:
        return 0.0
    return sum(components) / len(components)


def _minmax_normalize_2d(scores: np.ndarray) -> np.ndarray:
    """Min-max normalize each row of a 2-D array to [0, 1].

    If a row has identical values (mx == mn), returns zeros for that row.
    """
    mn = scores.min(axis=1, keepdims=True)
    mx = scores.max(axis=1, keepdims=True)
    span = mx - mn
    span[span == 0] = 1.0
    return (scores - mn) / span


def compute_hybrid_autoassign_scores(
    *,
    exemplar_embeddings: np.ndarray,
    exemplar_texts: list[str],
    code_embeddings: np.ndarray,
    code_texts: list[str],
    code_exemplar_map: dict[int, set[int]],
    all_exemplar_ids: list[int],
    all_exemplar_embeddings: np.ndarray,
    tokenizer: Callable[[str], list[str]],
    emb_weight: float = 0.6,
    direct_bm25_weight: float = 0.2,
    indirect_weight: float = 0.2,
    top_k: int = 20,
) -> np.ndarray:
    """Compute hybrid similarity scores for auto-assignment of exemplars to codes.

    For each (exemplar, code) pair returns a combined score in [0, 1]:

        combined = emb_weight * cosine
                 + direct_bm25_weight * direct_bm25
                 + indirect_weight * indirect_exemplar_agreement

    All component scores are min-max normalized to [0, 1] per exemplar
    so that the weighted sum stays in [0, 1].

    Parameters
    ----------
    exemplar_embeddings :
        (n, 384) L2-normalized exemplar embeddings.
    exemplar_texts :
        List of n strings: exemplar content + " " + keywords joined.
    code_embeddings :
        (m, 384) L2-normalized code embeddings.
    code_texts :
        List of m strings: code name + " " + definition.
    code_exemplar_map :
        Mapping of code_node_id → set of exemplar IDs already linked to that code.
    all_exemplar_ids :
        IDs of ALL exemplars (for indirect retrieval scoping).
    all_exemplar_embeddings :
        (n_all, 384) embeddings of all exemplars.
    tokenizer :
        Tokenizer callable for BM25.
    emb_weight, direct_bm25_weight, indirect_weight :
        Weights for each signal (default 0.6 / 0.2 / 0.2).
    top_k :
        Number of top similar exemplars to consider for indirect signal.

    Returns
    -------
    np.ndarray
        (n, m) float32 array of combined scores in [0, 1].
    """
    n = exemplar_embeddings.shape[0]
    m = code_embeddings.shape[0]

    if n == 0 or m == 0:
        return np.zeros((n, m), dtype="float32")

    # 1. Cosine similarity (direct semantic)
    cosine_sim = exemplar_embeddings @ code_embeddings.T  # (n, m)

    # 2. Direct BM25 (exemplar content vs code name+definition)
    from rank_bm25 import BM25Okapi

    code_corpus = [tokenizer(t) for t in code_texts]
    code_bm25 = BM25Okapi(code_corpus)
    direct_bm25 = np.zeros((n, m), dtype="float32")
    for i in range(n):
        query = tokenizer(exemplar_texts[i])
        raw = np.array(code_bm25.get_scores(query), dtype="float32")
        direct_bm25[i] = raw
    direct_bm25 = _minmax_normalize_2d(direct_bm25)

    # 3. Indirect exemplar agreement
    #    For each exemplar, find top-k most similar ALL exemplars (by cosine).
    #    For each code, compute fraction of top-k that belong to it.
    indirect = np.zeros((n, m), dtype="float32")
    if n > 0 and all_exemplar_embeddings.shape[0] > 0:
        # Cosine matrix: query exemplars × ALL exemplars
        all_sim = exemplar_embeddings @ all_exemplar_embeddings.T  # (n, n_all)

        for i in range(n):
            # Top-k most similar exemplars (indices into all_exemplar)
            top_idx = np.argsort(-all_sim[i])[:top_k]
            top_ids = set(all_exemplar_ids[idx] for idx in top_idx)

            for j, (code_id, linked_ids) in enumerate(code_exemplar_map.items()):
                if not linked_ids:
                    continue
                overlap = top_ids & linked_ids
                indirect[i, j] = len(overlap) / top_k

    indirect = _minmax_normalize_2d(indirect)

    # 4. Combined score
    combined = (
        emb_weight * cosine_sim
        + direct_bm25_weight * direct_bm25
        + indirect_weight * indirect
    )

    return combined.astype("float32")
