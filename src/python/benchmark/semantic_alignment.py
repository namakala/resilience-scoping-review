"""Level 2 metrics: code/theme semantic alignment.

Two metrics:
    2a: Max-pooled hybrid similarity — for each code in coder A, find
        best match in coder B using name + exemplar overlap.
    2b: Hungarian optimal matching — bipartite graph alignment between
        two coders' code sets.

Both accept precomputed embeddings for speed (embedding model is called
once per unique name, not repeatedly inside nested loops).
"""

from __future__ import annotations

from typing import Any

import numpy as np
from scipy.optimize import linear_sum_assignment


def _dot_sim(name_a: str, name_b: str, emb_cache: dict[str, np.ndarray]) -> float:
    """Cosine similarity from cache, clipped to [0, 1]."""
    ea = emb_cache.get(name_a)
    eb = emb_cache.get(name_b)
    if ea is None or eb is None:
        return 0.0
    return float(max(0.0, ea @ eb))


def _jaccard_sim(ex_a: set[str], ex_b: set[str]) -> float:
    """Jaccard similarity between two exemplar sets."""
    union = ex_a | ex_b
    return len(ex_a & ex_b) / len(union) if union else 0.0


def code_hybrid_similarity(
    name_a: str,
    name_b: str,
    exemplar_ids_a: set[str],
    exemplar_ids_b: set[str],
    emb_cache: dict[str, np.ndarray],
    name_weight: float = 0.4,
    ex_weight: float = 0.6,
) -> float:
    """Hybrid similarity between two code entities.

    Combines name cosine (from *emb_cache*) and exemplar Jaccard overlap.
    """
    nsim = _dot_sim(name_a, name_b, emb_cache)
    esim = _jaccard_sim(exemplar_ids_a, exemplar_ids_b)
    return name_weight * nsim + ex_weight * esim


def max_pooled_hybrid_similarity(
    code_map_a: dict[str, set[str]],
    code_map_b: dict[str, set[str]],
    emb_cache: dict[str, np.ndarray],
) -> dict[str, float]:
    """For each code in A, find best-matching code in B by hybrid similarity.

    Returns ``{code_a: best_similarity}``, plus ``"_macro_avg"`` key.
    """
    result: dict[str, float] = {}
    for coder_a_code, ex_a in code_map_a.items():
        best_sim = 0.0
        for coder_b_code, ex_b in code_map_b.items():
            sim = code_hybrid_similarity(
                coder_a_code, coder_b_code, ex_a, ex_b, emb_cache
            )
            if sim > best_sim:
                best_sim = sim
        result[coder_a_code] = best_sim

    if result:
        result["_macro_avg"] = float(np.mean(list(result.values())))
    return result


def _hungarian_similarity_matrix(
    codes_a: list[str],
    exemplar_map_a: dict[str, set[str]],
    codes_b: list[str],
    exemplar_map_b: dict[str, set[str]],
    emb_cache: dict[str, np.ndarray],
) -> np.ndarray:
    """Build (n, m) similarity matrix for Hungarian matching."""
    n = len(codes_a)
    m = len(codes_b)
    matrix = np.zeros((n, m), dtype=np.float64)
    for i, c_a in enumerate(codes_a):
        ex_a = exemplar_map_a.get(c_a, set())
        for j, c_b in enumerate(codes_b):
            ex_b = exemplar_map_b.get(c_b, set())
            matrix[i, j] = code_hybrid_similarity(c_a, c_b, ex_a, ex_b, emb_cache)
    return matrix


def hungarian_alignment(
    code_map_a: dict[str, set[str]],
    code_map_b: dict[str, set[str]],
    emb_cache: dict[str, np.ndarray],
) -> dict[str, Any]:
    """Bipartite optimal matching between two code sets.

    Uses Hungarian algorithm to maximise total similarity.
    """
    codes_a = list(code_map_a.keys())
    codes_b = list(code_map_b.keys())

    if not codes_a or not codes_b:
        return {
            "mean_weight": 0.0,
            "fraction_unmatched": 1.0,
            "matched_pairs": [],
            "unmatched_a": codes_a,
            "unmatched_b": codes_b,
        }

    sim = _hungarian_similarity_matrix(
        codes_a,
        code_map_a,
        codes_b,
        code_map_b,
        emb_cache,
    )

    cost = 1.0 - sim
    row_ind, col_ind = linear_sum_assignment(cost)

    matched_pairs: list[tuple[str, str, float]] = []
    matched_a: set[str] = set()
    matched_b: set[str] = set()
    weights: list[float] = []

    for r, c in zip(row_ind, col_ind):
        w = sim[r, c]
        matched_pairs.append((codes_a[r], codes_b[c], float(w)))
        matched_a.add(codes_a[r])
        matched_b.add(codes_b[c])
        weights.append(float(w))

    mean_w = float(np.mean(weights)) if weights else 0.0
    unmatched_a = [c for c in codes_a if c not in matched_a]
    unmatched_b = [c for c in codes_b if c not in matched_b]
    frac_unmatched = len(unmatched_a) / len(codes_a) if codes_a else 0.0

    return {
        "mean_weight": mean_w,
        "fraction_unmatched": frac_unmatched,
        "matched_pairs": matched_pairs,
        "unmatched_a": unmatched_a,
        "unmatched_b": unmatched_b,
    }
