---
title: "25 — keyword-embedding-generation"
description: "Encode keyword strings; store in embedding_cache"
updated_at: "2026-05-12"
phase: 4
---

# Feature 25: keyword-embedding-generation


---

## Description

Assuming keywords already extracted per exemplar (placeholder: dummy keyword list per exemplar for MVP), batch-encode concatenated keyword strings (e.g., `"keyword1 keyword2 keyword3"`). Store in `embedding_cache` with `entity_type='keyword'` and `entity_id=f"{exemplar_id}:{keyword_index}"` (keywords not globally unique). Immutable: same cache semantics as exemplars.

---

## Acceptance Criteria

- Keywords read from exemplars `keywords` column (list of strings)
- Each keyword string encoded individually OR all keywords for an exemplar concatenated and encoded as one vector (design choice documented)
- Cache key includes exemplar_id and keyword position to avoid collisions
- Number of keyword embeddings equals total keyword count across all exemplars
- Unit test verifies cache hit on second run without regeneration

---

## Dependencies

@docs/plan/24-exemplar-embedding-generation.md

---

## Implementation Notes

- Module: `src/python/semantic/embedding_generation.py` (same as 24 or separate)
- For MVP: keywords list per exemplar; encode each keyword separately
- Entity ID: `f"{exemplar_id}_kw_{i}"` (string)
- `keywords` column expected to be JSON list `["kw1", "kw2"]` in exemplars Parquet
- If keywords not yet extracted, placeholder returns `["stress", "mental", "health"]` per exemplar

---

**References:** ADR-005
