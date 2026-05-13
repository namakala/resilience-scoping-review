---
title: "29 — neighbor-discovery-service"
description: "k-nearest neighbors by embedding similarity within tag scope"
updated_at: "2026-05-13"
phase: 4
---

# Feature 29: neighbor-discovery-service


---

## Description

Given an entity (code/theme) and its embedding, find k-nearest neighbors within the same tag scope. Uses `compute_similarity` on candidate subset from `get_scope_for_tag`. Optionally filters by type (code-only or theme-only). Returns list of `(neighbor_id, similarity_score)`.

---

## Acceptance Criteria

- Neighbors all have similarity > 0.5 (unit vectors)
- Query entity excluded from results
- Default k=5; configurable up to 20
- Used by HITL CLI to show "similar codes" during review
- Caches neighbor lists for 5 minutes to avoid repeated computation during review session

---

## Dependencies

@docs/plan/28-hybrid-retrieval-engine.md

---

## Implementation Notes

- Module: `src/python/semantic/neighbors.py`
- Function: `find_neighbors(entity_id: int, entity_type: str, k: int=5) → list[tuple[int, float]]`
- Get entity tag via `get_node(entity_id)['tag']`
- Scope = `get_scope_for_tag(tag)`; candidate ids = all entities of same type whose tag in scope
- Compute cosine similarity between query embedding and all candidate embeddings
- Exclude query id; sort by similarity desc; take top-k
- In-memory cache: `{(entity_id, k): (neighbors, timestamp)}`; expire after 300s
- Similarity threshold: filter >=0.5; if fewer than k, return all above threshold

---

**References:** ADR-006
