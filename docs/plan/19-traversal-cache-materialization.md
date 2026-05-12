---
title: "19 — traversal-cache-materialization"
description: "Precompute and store ancestors, descendants, subtree aggregates in DuckDB"
updated_at: "2026-05-12"
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
- Compute on startup: iterate all tags → compute via NetworkX traversal → join with exemplars table
- `subtree_exemplar_ids`: find all exemplars whose tag is in `get_subtree(tag)`
- `get_cached_subtree(tag)`: read row; if `stale=True`, recompute and update
- Batch query: `SELECT * FROM traversal_cache WHERE tag IN (?, ?, ...)`

---

**References:** ADR-012
