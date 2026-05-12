---
title: "09 — bm25-index-serialization"
description: "Pickle-based BM25 index persistence and loading"
updated_at: "2026-05-12"
phase: 1
---

# Feature 09: bm25-index-serialization


---

## Description

Implement pickle-based persistence for BM25 index. Build index from keyword corpus; store with metadata: `corpus` (list of keyword strings per exemplar), `bm25_object`, `entity_map` (exemplar_id → index), `tokenizer_config`. Provide `save_bm25(path)` and `load_bm25(path)` functions.

---

## Acceptance Criteria

- BM25 object serialized and deserialized without loss of scoring capability
- Round-trip: `save → load → get_scores(query)` produces identical scores (±1e-6)
- Stored file includes version number and creation timestamp
- Rebuild function detectable if corpus changes (via hash check)
- Storage size < 100 MB for 1000 exemplars

---

## Dependencies

@docs/plan/05-csv-to-parquet-converter.md
@docs/plan/06-artifact-loaders.md

---

## Implementation Notes

- Module: `src/python/semantic/bm25_index.py`
- Use `rank_bm25` package: `BM25Okapi(corpus)`
- Normalize scores: `(scores - min) / (max - min)` to [0,1]
- Store at `data/processed/bm25_index.pkl` with pickle protocol 4
- Metadata dict: `{"version":"1.0", "created_at":"...", "corpus_hash":"..."}`

---

**References:** ADR-006 (Retrieval Strategy)
