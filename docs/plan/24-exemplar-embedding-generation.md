---
title: "24 — exemplar-embedding-generation"
description: "Batch-encode all exemplar content; store in embedding_cache; immutable"
updated_at: "2026-05-13"
phase: 4
---

# Feature 24: exemplar-embedding-generation


---

## Description

Batch-encode all exemplar `content` strings from `load_exemplars()`. Compute `content_hash` per exemplar (SHA256(content)). Store embedding in `embedding_cache` table with `entity_id=exemplar_id`, `entity_type='exemplar'`, `model_hash`, `content_hash`. Mark as immutable: never regenerate unless `content_hash` mismatches or model version changes.

---

## Acceptance Criteria

- Process 1000 exemplars in <2 minutes on CPU (Intel i5 or equivalent)
- Embeddings stored as BLOB (`.tobytes()`); retrieval returns identical array (`np.array_equal`)
- Cache lookup before generation: if `(entity_id, type)` exists and `content_hash` matches, skip regeneration
- Progress bar displayed via `tqdm`
- After completion, `SELECT COUNT(*) FROM embedding_cache WHERE entity_type='exemplar'` equals number of exemplars

---

## Dependencies

@docs/plan/23-sentence-transformer-initialization.md
@docs/plan/06-artifact-loaders.md
@docs/plan/08-embedding-cache-schema.md

---

## Implementation Notes

- Module: `src/python/semantic/embedding_generation.py`
- Batch size: 32 or 64 depending on memory
- Query: `SELECT entity_id, content_hash FROM embedding_cache WHERE entity_type='exemplar' AND entity_id IN (...)` to find existing
- Compute hash: `hashlib.sha256(content.encode()).hexdigest()[:16]`
- Log embedding time per exemplar; total duration

---

**References:** ADR-005
