---
title: "28 — hybrid-retrieval-engine"
description: "Four-stage: scope → BM25 → embeddings → weighted rerank"
updated_at: "2026-05-12"
phase: 4
---

# Feature 28: hybrid-retrieval-engine


---

## Description

Four-stage retrieval pipeline (ADR-006):
1. **Graph scope** — Input: tag identifier; restrict candidates to entities whose tag is in `get_scope_for_tag(tag)` (or that belong to tags in that subtree).
2. **BM25 retrieval** — Compute BM25 scores for candidates using their keyword sets; take top-50.
3. **Embedding retrieval** — Compute cosine similarity between query embedding (composed of query keywords or reference entity) and candidate embeddings; take top-50.
4. **Rerank** — Combine: `final_score = 0.5*emb_score + 0.3*proximity_boost + 0.2*bm25_score`. `proximity_boost` = 1.0 if candidate tag matches query tag exactly, else decays by depth distance.

Return sorted list of `(entity_id, final_score)`.

---

## Acceptance Criteria

- Scope filtering reduces candidate set by ≥70% for deep tags
- BM25 and embedding stages each produce exactly 50 candidates (or fewer if pool smaller)
- Final ranking respects combined score (descending)
- Proximity boost computed: `boost = 1 / (1 + depth_distance)` where depth_distance = |candidate.depth - query.depth|
- End-to-end retrieval for query with 5 keywords completes in <200ms for 1000 candidates
- Deterministic: same inputs → same order (tie-breaking by entity_id)

---

## Dependencies

@docs/plan/22-scope-restriction-helper.md
@docs/plan/26-bm25-index-builder.md
@docs/plan/27-embedding-similarity-computation.md

---

## Implementation Notes

- Module: `src/python/semantic/retrieval.py`
- Function: `hybrid_retrieve(query_tag: str, query_keywords: list[str], query_embedding: np.ndarray, candidate_type: str, k: int=50) → list[tuple[int, float]]`
- Steps:
  1. `candidates = get_candidates_in_scope(query_tag)` via scope helper
  2. `bm25_scores = get_bm25_scores(query_keywords)`; `top50_bm25 = top_k(bm25_scores, 50)`
  3. `emb_scores = cosine_similarity(query_embedding, candidate_embeddings)`; `top50_emb = top_k(emb_scores, 50)`
  4. `union = set(top50_bm50) ∩ set(top50_emb)`; if <k, fill from next best in each
  5. For each candidate, compute `depth_distance = abs(get_depth(candidate_tag) - get_depth(query_tag))`
  6. `proximity_boost = 1.0 / (1 + depth_distance)`
  7. `final = 0.5*emb_norm + 0.3*proximity_boost + 0.2*bm25_norm` (normalize each score subcomponent to [0,1] before weighting)
- Return sorted: `sorted(union_scores.items(), key=lambda x: x[1], reverse=True)[:k]`

---

**References:** ADR-006
