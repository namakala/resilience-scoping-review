---
title: "26 — bm25-index-builder"
description: "Build BM25 over exemplar keyword sets; normalize scores; serialize"
updated_at: "2026-05-13"
phase: 4
---

# Feature 26: bm25-index-builder

**Status:** Implemented

---

## Description

Build BM25 lexical index over exemplar keyword sets. Tokenize keywords via configurable pipeline (lowercase, strip punctuation, remove stopwords). Create corpus as list of keyword-list-per-document. Train BM25 on corpus. Serialize index including: `corpus` (list of list[str]), `bm25_object`, `entity_map` (exemplar_id → corpus index), `tokenizer_config`. Store at `data/processed/bm25_index.pkl`.

---

## Acceptance Criteria

- BM25 scores normalized to [0, 1] via min-max scaling across all documents for a query
- `get_scores(query: str) → dict[exemplar_id: float]` returns normalized scores (takes raw string; tokenized internally via configured pipeline)
- Round-trip serialization preserves scores (load → score identical to pre-save, verified in `save_bm25()`)
- Index built in <1 minute for 1000 exemplars (tested)
- Query for 5 keywords returns scores for all exemplars in <100ms
- Stopwords optionally removed (configurable via `BM25_TOKENIZER_CONFIG` env var)

---

## Dependencies

@docs/plan/06-artifact-loaders.md
@docs/plan/25-keyword-embedding-generation.md

---

## Implementation Summary

### Modules

Six files under `src/python/semantic/`, not a single `bm25.py`:

| Module | Purpose | Key exports |
|--------|---------|-------------|
| `tokenizer.py` | Configurable tokenization pipeline | `_TOKENIZER` callable, `_build_tokenizer()`, `_parse_tokenizer_config()` |
| `corpus.py` | Corpus construction from keywords | `_build_corpus_and_map()`, `_compute_corpus_hash()` |
| `index_builder.py` | BM25 training and orchestration | `build_index()` |
| `persistence.py` | Atomic save/load with validation | `save_bm25()`, `load_bm25()` |
| `api.py` | Public scoring API | `get_scores()`, `get_top_n()`, `get_index_info()` |
| `cache.py` | In-memory singleton cache | `clear_cache()` |
| `exceptions.py` | Error types | `BM25IndexError`, `IndexCorruptedError` |

### Key Design Decisions

- **Tokenizer** is configurable via `BM25_TOKENIZER_CONFIG` env var with toggle pipeline: `lowercase`, `strip_punctuation`, `split_by_space` (required), `remove_stopword`. Default: `lowercase,split_by_space`.
- **Corpus** is built from `keywords.parquet` via `_build_corpus_and_map()` — groups keywords by exemplar_id, joins them into a string, then re-tokenizes through the pipeline for consistency.
- **Index persistence** uses `pickle` with atomic write (tmp file + rename) and round-trip score validation (±1e-6 tolerance).
- **Corpus hash** (`SHA256[:16]`) enables rebuild detection — `load_bm25()` validates stored hash against current keywords, raising `IndexCorruptedError` on mismatch.
- **Score normalization**: `(raw - min) / (max - min)` → [0, 1]; all-equal scores return zeros.
- **Public API** accepts `str` (raw query), not `list[str]` — the tokenizer is the single source of truth for normalization.

### Tests

`tests/unit/semantic/bm25_index_test.py` — 17 tests across two test classes:

- `TestBM25Tokenizer` (7 tests): toggle configs, stopword removal, punctuation stripping, invalid toggle rejection
- `TestBM25IndexBuildAndSave` (10 tests): build, load, round-trip, normalization, zero-case, metadata, hash mismatch, empty corpus, size constraint, top-n sorting

---

**References:** ADR-006
