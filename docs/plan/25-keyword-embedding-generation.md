---
title: "25 — keyword-extraction-and-embedding"
description: "Extract keywords via KeyBERT; encode and cache embeddings"
updated_at: "2026-05-13"
phase: 4
---

# Feature 25: Keyword Extraction and Embedding

Two-stage feature: (1) extract keywords via KeyBERT, (2) batch-encode keyword strings into `embedding_cache`.

---

## Description

**Extraction stage:** `extract_keywords()` uses KeyBERT with `all-MiniLM-L6-v2` to extract top-5 keywords per exemplar via semantic similarity and MMR diversity. Writes immutable `keywords.parquet`. Extraction is the sole method (no LLM refinement phase).

**Embedding stage:** `generate_keyword_embeddings()` reads `keywords.parquet` via `load_keywords()`, encodes each keyword string individually, and stores in `embedding_cache` with `entity_type='keyword'` and `entity_id=f"{exemplar_id}_kw_{i}"`. Immutable: same cache semantics as exemplars.

---

## Acceptance Criteria

- KeyBERT extracts top-5 keywords per exemplar with MMR diversity=0.5, ngram (1,2)
- Extraction skipped on re-run (immutability); `force_rebuild` overrides
- `keywords.parquet` written with schema: keyword_id, exemplar_id, keyword_text, frequency
- Embedding count equals total keyword rows across all exemplars
- Cache key includes exemplar_id and keyword position to avoid collisions
- Unit test verifies cache hit on second run without regeneration
- Empty keywords list yields zero embeddings (no-op, not error)

---

## Dependencies

@docs/plan/24-exemplar-embedding-generation.md

---

## Implementation Notes

- Module: `src/python/semantic/keyword_extraction.py` (extraction) + `embedding_generation.py` (embedding)
- KeyBERT config: `model='all-MiniLM-L6-v2'`, `keyphrase_ngram_range=(1,2)`, `use_mmr=True`, `diversity=0.5`, `top_n=5`
- Score → frequency: `int(round(score * 10000))` stored as Int32
- Entity ID: `f"{exemplar_id}_kw_{i}"` (string)
- Source: `keywords.parquet` via `load_keywords()`, not exemplars column

---

**References:** ADR-005
