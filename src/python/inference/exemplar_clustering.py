"""Cluster exemplars by pairwise embedding similarity for batch code inference.

Uses threshold-based transitive closure (Union-Find) to group similar
exemplars. Each cluster becomes one LLM batch, producing one abstract code.
Leftover exemplars below threshold with all clusters form a misc batch.
"""

from __future__ import annotations

from collections import defaultdict

import duckdb
import numpy as np
from persistence.embedding_cache import get_embedding
from utils.logging import get_logger

logger = get_logger(__name__)

__all__ = ["compute_pairwise_similarity", "cluster_by_similarity"]


def compute_pairwise_similarity(
    exemplars: list,
    con: duckdb.DuckDBPyConnection,
) -> np.ndarray:
    """Compute (n, n) pairwise cosine similarity matrix for exemplar embeddings.

    Each exemplar must have an ``.id`` attribute (int) used to look up
    cached embeddings.  Returns a float32 array of shape (n, n).

    Raises
    ------
    ValueError
        If no embeddings are found in the cache.
    """
    n = len(exemplars)
    if n == 0:
        return np.zeros((0, 0), dtype="float32")

    embeddings: list[np.ndarray] = []
    for ex in exemplars:
        emb = get_embedding(con, str(ex.id), "exemplar")
        if emb is None:
            raise ValueError(f"Embedding not found for exemplar id={ex.id}")
        embeddings.append(emb)

    matrix = np.stack(embeddings, axis=0)
    sim = matrix @ matrix.T
    np.fill_diagonal(sim, 1.0)
    return sim.astype("float32")


def cluster_by_similarity(
    exemplars: list,
    similarity_matrix: np.ndarray,
    threshold: float,
    min_cluster_size: int = 5,
) -> tuple[list[list], list]:
    """Group *exemplars* into clusters using threshold-based transitivity.

    Algorithm
    ---------
    1. Build adjacency from pairwise cosine similarity >= *threshold*.
    2. Union-Find transitive closure over the adjacency graph.
    3. Connected components sorted by size descending.

    For each component (as a cluster seed):

    - If its size already >= *min_cluster_size* → emit as cluster.
    - If its size < *min_cluster_size* → pull the nearest unassigned
      items (by max cosine to any seed member) until *min_cluster_size*
      is reached or no items remain.

    If a seed cannot reach *min_cluster_size* after exhausting all
    remaining items, all leftover items (including this seed) become
    the misc cluster.

    Parameters
    ----------
    exemplars :
        List of objects with an ``.id`` attribute.
    similarity_matrix :
        (n, n) float32 array of pairwise cosine similarities.
    threshold :
        Similarity threshold [0, 1].  Pairs above this are adjacent.
    min_cluster_size :
        Minimum exemplars per cluster (default 5).

    Returns
    -------
    tuple[list[list], list]
        ``(clusters, misc)`` where *clusters* is a list of exemplar lists
        (one per cluster) and *misc* is a single list of leftover exemplars
        (may be empty).  If all exemplars are below threshold with every
        other exemplar, *clusters* is empty and *misc* contains all items.
    """
    n = len(exemplars)
    if n == 0:
        return [], []

    # Step 1: Union-Find on adjacency graph
    parent = list(range(n))

    def _find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def _union(x: int, y: int) -> None:
        px, py = _find(x), _find(y)
        if px != py:
            parent[px] = py

    adj = similarity_matrix >= threshold
    for i in range(n):
        for j in range(i + 1, n):
            if adj[i, j]:
                _union(i, j)

    # Step 2: Group indices by root, sort by size descending
    by_root: dict[int, list[int]] = defaultdict(list)
    for i in range(n):
        by_root[_find(i)].append(i)
    groups = sorted(by_root.values(), key=len, reverse=True)

    # Step 3: Greedy cluster formation
    assigned: set[int] = set()
    clusters: list[list[int]] = []
    misc_indices: list[int] = []

    for group in groups:
        cluster = [i for i in group if i not in assigned]
        if not cluster:
            continue

        # Singletons with no edges above threshold → misc
        if len(cluster) < 2:
            misc_indices.extend(cluster)
            continue

        # Pad if below min_cluster_size
        while len(cluster) < min_cluster_size:
            unassigned = [i for i in range(n) if i not in assigned and i not in cluster]
            if not unassigned:
                break
            best = max(
                unassigned,
                key=lambda ui: max(similarity_matrix[ui, ci] for ci in cluster),
            )
            cluster.append(best)

        if len(cluster) >= min_cluster_size:
            clusters.append(cluster)
            assigned.update(cluster)
        else:
            # Could not reach min_cluster_size — remaining items go to misc
            misc_indices.extend(cluster)
            break

    # Step 4: Any remaining unassigned items → misc
    remaining = sorted(set(range(n)) - assigned - set(misc_indices))
    misc_indices.extend(remaining)
    misc = [exemplars[i] for i in misc_indices]
    result = [[exemplars[i] for i in c] for c in clusters]

    logger.info(
        "Clustered %d exemplars into %d cluster(s) + %d misc item(s)",
        n,
        len(result),
        len(misc),
    )
    return result, misc
