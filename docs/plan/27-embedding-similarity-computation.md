---
title: "27 — embedding-similarity-computation"
description: "Cosine similarity matrix between entity embeddings"
updated_at: "2026-05-12"
phase: 4
---

# Feature 27: embedding-similarity-computation


---

## Description

Compute cosine similarity matrix between two sets of entity IDs (codes, themes, etc.). Function: `compute_similarity(entity_ids: list[int], entity_type: str) → np.ndarray[float32]` of shape `(n, n)`. Uses cached embeddings from `embedding_cache`. Symmetric matrix, diagonal = 1.0.

---

## Acceptance Criteria

- Retrieves embeddings from cache; raises `CacheMissError` if any missing
- Returns float32 matrix; values in [-1, 1] (unit vectors → [0, 1])
- For n=100, computation <500ms on CPU
- Handles single entity (returns 1x1 matrix with 1.0)
- Unit test with known vectors produces exact expected cosine values

---

## Dependencies

@docs/plan/24-exemplar-embedding-generation.md
@docs/plan/08-embedding-cache-schema.md

---

## Implementation Notes

- Module: `src/python/semantic/similarity.py`
- Load all embeddings for ids: `embeddings = [get_embedding(eid) for eid in entity_ids]` → stack to (n, 384)
- Cosine: `cos_sim = (A @ B.T) / (np.linalg.norm(A, axis=1, keepdims=True) * np.linalg.norm(B, axis=1, keepdims=True).T)`
- Since vectors unit-normalized, cos_sim = A @ B.T
- Diagonal set to 1.0 explicitly (avoid -1 from numerical drift)

---

**References:** ADR-005
