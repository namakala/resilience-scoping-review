---
title: "19 — traversal-cache-materialization"
description: "Precompute and store ancestors, descendants, subtree aggregates in DuckDB"
updated_at: "2026-05-14"
phase: 3
---

# Feature 19: traversal-cache-materialization


---

## Description

Precompute and store in DuckDB `traversal_cache` table: for each tag, store arrays (JSON) of `ancestors`, `descendants`, `subtree_exemplar_ids` (all exemplar IDs under that tag's subtree), `subtree_code_ids`, `subtree_theme_ids`. Compute once at system startup or when ontology changes.

---

## Acceptance Criteria

- Cache table populated for every tag
- Each JSON array deserializable to Python list
- `subtree_exemplar_ids` computed by joining tags→exemplars (deduplicated)
- `subtree_code_ids` and `subtree_theme_ids` initially empty (filled as codes/themes are created)
- Cache query function `get_cached_subtree(tag)` reads from DuckDB; falls back to recompute if missing
- Storage overhead: <10 MB for 1000 tags

---

## Dependencies

@docs/plan/18-ontology-traversal-ops.md

---

## Implementation Notes

- Module: `src/python/ontology/cache.py`
- Table schema: `tag TEXT PRIMARY KEY, ancestors JSON, descendants JSON, subtree_exemplars JSON, subtree_codes JSON, subtree_themes JSON, stale BOOLEAN DEFAULT FALSE`
- Feature 18 (`ontology.traversal`) implements in-memory `lru_cache` for traversal ops via NetworkX; Feature 19 is a separate persistence layer on top, not a replacement
- This feature builds on top of Feature 18's public API (`get_ancestors`, `get_descendants`, `get_subtree`) for computation, then stores results in DuckDB
- Compute on startup: iterate all tags → call `get_ancestors(tag)`, `get_descendants(tag)` → store results in DuckDB
- `subtree_exemplar_ids`: find all exemplars whose tag is in `get_subtree(tag)`
- `get_cached_subtree(tag)`: read row from DuckDB; if row missing or `stale=True`, recompute using Feature 18 functions and update
- `invalidate_cache_for_tag(tag)`: sets `stale=TRUE` for that tag (used by Feature 20)
- `clear_duckdb_cache()`: deletes all rows from traversal_cache (test cleanup / full rebuild)
- Batch query: `SELECT * FROM traversal_cache WHERE tag IN (?, ?, ...)`

---

**References:** ADR-012
