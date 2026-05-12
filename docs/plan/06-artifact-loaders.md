---
title: "06 — artifact-loaders"
description: "Lazy-load exemplars, tags, keywords from Parquet"
updated_at: "2026-05-12"
phase: 1
---

# Feature 06: artifact-loaders

**Status:** Implemented — commit `e3beaa9`

---

## Description

Implement lazy-loading functions: `load_exemplars() → Polars LazyFrame`, `load_tags() → Polars LazyFrame`, `load_keywords() → Polars LazyFrame`. Each function reads from `data/processed/*.parquet` and adds computed columns: `content_hash` (SHA256 of content), `keyword_count`, etc.

---

## Implementation Summary

- **Module:** `src/python/persistence/loaders.py` (172 lines)
- **Export:** Added to `src/python/persistence/__init__.py`
- **Tests:** `tests/unit/persistence/loaders_test.py` (19 tests)
- **Caching:** `@functools.lru_cache(maxsize=1)` per loader; `clear_cache()` utility
- **Defensive recompute:** `content_hash` always derived from `content` column (ADR-002)
- **Tag enrichment:** `parent` (string before last dot or empty), `depth` (segment count)
- **Keywords:** Graceful absent-file handling — returns empty LazyFrame with correct schema

---

## Acceptance Criteria

- Functions return LazyFrame, not eager DataFrame (deferred execution)
- Schema matches: exemplars (`id: int64, document: str, tag: str, content: str, keywords: list[str], content_hash: str`), tags (`tag: str, parent: str, description: str, depth: int`), keywords (`keyword_id: int64, exemplar_id: int64, keyword_text: str, frequency: int32`)
- `content_hash` consistently computed (hex digest)
- Loaders cache in memory after first call (singleton pattern) to avoid repeated I/O
- Unit test with sample Parquet file verifies lazy evaluation (no compute until `.collect()`)

---

## Dependencies

@docs/plan/05-csv-to-parquet-converter.md

---

## Implementation Notes

- Module: `src/python/persistence/loaders.py`
- Cache via `functools.lru_cache` or module-level variable
- `content_hash = hashlib.sha256(content.encode()).hexdigest()[:16]`
- Keywords loaded from separate `keywords.parquet` (created later)

---

**References:** ADR-002, ADR-009
