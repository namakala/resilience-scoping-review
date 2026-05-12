---
title: "26 — bm25-index-builder"
description: "Build BM25 over exemplar keyword sets; normalize scores; serialize"
updated_at: "2026-05-12"
phase: 4
---

# Feature 26: bm25-index-builder


---

## Description

Build BM25 lexical index over exemplar keyword sets. Tokenize keywords (lowercase, remove punctuation). Create corpus as list of keyword-list-per-document. Train BM25 on corpus. Serialize index including: `corpus` (list of list[str]), `bm25_object`, `entity_map` (exemplar_id → corpus index), `tokenizer_config`. Store at `data/processed/bm25_index.pkl`.

---

## Acceptance Criteria

- BM25 scores normalized to [0, 1] via min-max scaling across all documents for a query
- `get_scores(query_keywords: list[str]) → dict[exemplar_id: float]` returns normalized scores
- Round-trip serialization preserves scores (load → score identical to pre-save)
- Index built in <1 minute for 1000 exemplars
- Query for 5 keywords returns scores for all exemplars in <100ms
- Stopwords optionally removed (configurable)

---

## Dependencies

@docs/plan/06-artifact-loaders.md
@docs/plan/25-keyword-embedding-generation.md

---

## Implementation Notes

- Module: `src/python/semantic/bm25.py`
- `corpus[i] = exemplar_keywords_list[i]` (already tokenized)
- `bm25 = BM25Okapi(corpus)`
- `scores = bm25.get_scores(query)` → `(scores - min) / (max - min)`
- Entity map: `exemplar_id_by_index[i] = exemplar_id` (from exemplars table)
- Serialize with `pickle.dump({'bm25': bm25, 'corpus': corpus, 'entity_map': entity_map})`

---

**References:** ADR-006
