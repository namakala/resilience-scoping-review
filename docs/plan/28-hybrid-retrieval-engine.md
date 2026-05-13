---
title: "28 — hybrid-retrieval-engine"
description: "Four-stage: scope -> BM25 (exemplars only) -> embeddings -> union+rerank"
updated_at: "2026-05-13"
phase: 4
---

# Feature 28: hybrid-retrieval-engine

---

## Description

Four-stage retrieval pipeline (ADR-006):
1. **Graph scope** — Input: tag identifier; resolve candidate entity IDs in
   the tag's ontology subtree.
2. **BM25 retrieval** — For exemplar candidates only: compute BM25 scores
   from keyword sets; take top-50. Skipped for code/theme/interpretation
   types (weights renormalized).
3. **Embedding retrieval** — Compute cosine similarity between query
   embedding and candidate embeddings; take top-50.
4. **Rerank** — Union top-k from BM25 (if applicable) and embeddings.
   Compute weighted score per candidate:
   - Exemplars: `final = 0.5*emb + 0.3*prox + 0.2*bm25`
   - Non-exemplars: `final = 0.625*emb + 0.375*prox`
   - `proximity_boost = 1.0 / (1 + depth_distance)` where
     `depth_distance = |candidate.depth - query.depth|`

Return sorted list of `(entity_id, final_score)` descending, with
tie-breaking by `entity_id`.

---

## Acceptance Criteria

- Scope filtering reduces candidate set by >=70% for deep tags
- BM25 and embedding stages each produce exactly 50 candidates (or
  fewer if pool smaller)
- Final ranking respects combined score (descending)
- Proximity boost: `boost = 1 / (1 + depth_distance)`
- End-to-end retrieval for query with 5 keywords completes in <200ms
  for 1000 candidates
- Deterministic: same inputs -> same order (tie-breaking by entity_id)
- Non-exemplar types (code, theme, interpretation) skip BM25 stage and
  use renormalized weights `(0.625, 0.375)`

---

## Dependencies

@docs/plan/22-scope-restriction-helper.md
@docs/plan/26-bm25-index-builder.md
@docs/plan/27-embedding-similarity-computation.md

---

## Implementation Notes

- **Package:** `src/python/semantic/retrieval/`
  - `__init__.py` — re-exports `hybrid_retrieve` from `api.py`
  - `api.py` — public `hybrid_retrieve()` orchestrator
  - `candidates.py` — `resolve_candidate_ids()` scope + entity lookup
  - `scoring.py` — BM25, embedding scoring, `get_depth()`
  - `weights.py` — `WeightConfig` namedtuple + `select_weights()`
  - `AGENTS.md` — sub-module documentation
- **Tests:** `tests/unit/semantic/retrieval_test.py`
- **Function:**
  ```
  hybrid_retrieve(
      query_tag: str,
      query_keywords: list[str],
      query_embedding: np.ndarray,
      candidate_type: str,
      con: duckdb.DuckDBPyConnection,
      k: int = 50,
      model_hash: Optional[str] = None,
  ) -> list[tuple[int, float]]
  ```

### Sub-module API

- `candidates.resolve_candidate_ids(tag, type, con)` ->
  `(set[int], dict[int, str])` — entity IDs + entity-to-tag map.
- `scoring.get_bm25_scores_for_candidates(keywords, ids, k)` ->
  `dict[int, float]` — BM25 top-k filtered by scope.
- `scoring.get_embedding_scores(query_emb, ids, type, con, hash, k)` ->
  `(dict[int, float], set[int])` — load embeddings, dot product,
  return scores + top-k set.
- `scoring.get_depth(tag)` -> `int` — ontology depth via DAG.
- `weights.select_weights(candidate_type)` -> `WeightConfig` —
  weight triplet for rerank formula.

### Private helpers in api.py

- `_score_bm25_or_default()` — runs BM25 or returns empty defaults
  with renormalized weights for non-exemplar types.
- `_rerank()` — union candidates, compute weighted score with
  proximity boost, sort, return top-k.

### Algorithm steps

1. **Scope resolution**: `candidate_ids, entity_tag_map =
   _resolve_candidate_ids(query_tag, candidate_type, con)`
2. **BM25 (exemplar only)**: `bm25_scores =
   _get_bm25_scores_for_candidates(query_keywords, candidate_ids, k)`.
   Non-exemplar: skip, use renormalized weights `(0.625, 0.375)`.
3. **Embedding**: `emb_scores, top_emb =
   _get_embedding_scores(query_embedding, candidate_ids, candidate_type,
   con, model_hash, k)`
4. **Union + rerank**:
   - `pool = set(top_bm25) | set(top_emb)`
   - For each `eid` in pool:
     - `tag = entity_tag_map[eid]`
     - `depth_dist = abs(_get_depth(tag) - _get_depth(query_tag))`
     - `prox = 1.0 / (1.0 + depth_dist)`
     - `final = w_emb * emb[eid] + w_prox * prox + w_bm25 * bm25[eid]`
   - `sorted(pool, key=lambda eid: (-final[eid], eid))[:k]`

### Normalization

- BM25 scores already normalized to `[0, 1]` by `get_scores()`.
- Embedding cosine is naturally in `[0, 1]` (L2-normalized vectors,
  non-negative text embeddings).
- Proximity boost `1/(1+depth_dist)` in `(0, 1]`.
- No additional normalization needed before weighting.

### Weights

- Exemplar: `w_emb=0.5, w_prox=0.3, w_bm25=0.2`
- Non-exemplar: `w_emb=0.625, w_prox=0.375` (renormalized from
  removal of 0.2 BM25 term)

### Edge cases

- Empty candidate set -> return `[]`
- All candidates at same depth -> proximity = 1.0 for all (weighted
  formula still produces valid ranking)
- Embedding cache miss for some candidates -> skip that entity, log
  warning, continue with remainder
- Unknown candidate types -> treated as non-exemplar (nodes table
  likely returns empty)

---

**References:** ADR-006
