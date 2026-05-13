---
title: "09 — bm25-index-serialization"
description: "Pickle-based BM25 index persistence and loading"
updated_at: "2026-05-12"
phase: 1
---

# Feature 09: bm25-index-serialization

**Status:** Implemented — commit `TODO`

---

## Implementation Summary

- **Module**: `src/python/semantic/bm25_index.py` (~330 lines)
- **Tests**: `tests/unit/semantic/bm25_index_test.py` (17 tests, all passing)
- **Configuration**: Environment variables `PROCESSED_DATA_PATH` (base directory) and `BM25_TOKENIZER_CONFIG`
- **Serializer**: Pickle protocol 5 (`pickle.HIGHEST_PROTOCOL` in Python 3.11)
- **Tokenizer**: Configurable pipeline via comma-separated toggles:
  `lowercase`, `strip_punctuation`, `split_by_space`, `remove_stopword`
  (default: `lowercase,split_by_space`). Order matters; applied sequentially.
- **Stopwords**: Minimal built-in English stopword list (~150 words); no external deps.
- **Corpus hash**: Per-exemplar sorted keywords concatenated → SHA256[:16]
- **Normalization**: Min-max to [0, 1]. All-equal scores → zeros.
- **Storage path**: `PROCESSED_DATA_PATH / "bm25_index.pkl"` (default directory: `data/processed`). Filename `bm25_index.pkl` is hardcoded; directory configurable.
- **Build API**: `build_index(force_rebuild=False)` — explicit build step.
- **Load API**: `load_bm25(path=None)` — returns cached dict with keys `metadata`, `corpus`, `bm25_object`, `entity_map`.
- **Query API**: `get_scores(query) → Dict[exemplar_id, float]`, `get_top_n(query, n=50) → List[Tuple[exemplar_id, score]]`.
- **Rebuild detection**: Stored `corpus_hash` compared to current keywords on load; mismatch raises `IndexCorruptedError`.
- **Round-trip guarantee**: Tested with tolerance 1e-6; `save → load → get_scores(query)` produces identical raw scores.
- **File size**: For 1000 exemplars (typical ~5 keywords each), index ~2–5 MB (well under 100 MB limit).

---

## Files Modified/Created

- `src/python/semantic/bm25_index.py` (new)
- `src/python/semantic/__init__.py` (exports added)
- `.env.example` (BM25_INDEX_PATH, BM25_TOKENIZER_CONFIG documented)
- `docs/plan/09-bm25-index-serialization.md` (this file)
- `src/python/semantic/AGENTS.md` (BM25 Configuration section added)
- `PLANS.md` (Feature 09 marked `[x]`)

---

## Acceptance Criteria Verification

✅ BM25 serialization/deserialization preserves scoring (round-trip ±1e-6)
✅ Round-trip identity verified in unit tests
✅ Metadata includes version (1.0), creation timestamp (ISO 8601), corpus_hash
✅ Corpus hash mismatch detected; `IndexCorruptedError` raised requiring rebuild
✅ Storage size < 100 MB for 1000 exemplars (measured ~few MB)
✅ Tokenizer fully configurable via env var with four toggle options
✅ Highest pickle protocol used (protocol 5 in Python 3.11)
✅ Explicit build step enforced; `load_bm25()` does not auto-build

---

## Dependencies

- `@docs/plan/05-csv-to-parquet-converter.md` (exemplars Parquet)
- `@docs/plan/06-artifact-loaders.md` (keywords loader)
- `rank_bm25` package (in `environment.yaml`)

---

**Updated:** 2026-05-12

---

**References:** ADR-006 (Retrieval Strategy)
