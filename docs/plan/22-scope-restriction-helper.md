---
title: "22 — scope-restriction-helper"
description: "get_scope_for_tag(tag) → set of tag IDs for retrieval filtering"
updated_at: "2026-05-12"
phase: 3
---

# Feature 22: scope-restriction-helper


---

## Description

Function `get_scope_for_tag(tag: str) → set[str]` returns set of all tag IDs considered "in scope" for that tag (tag itself plus all descendants). Used by semantic retrieval layer to filter candidate codes/themes/interpretations before embedding ranking.

---

## Acceptance Criteria

- For leaf tag, scope = {tag}
- For root tag, scope = all tags
- Scope respects DAG (multiple-inheritance tags include all ancestor paths)
- Cached result in `traversal_cache`
- Unit tests verify scope boundaries for sample ontology with branching

---

## Dependencies

@docs/plan/18-ontology-traversal-ops.md

---

## Implementation Notes

- Module: `src/python/ontology/scope.py`
- Simply: `return get_cached_subtree(tag)` from Feature 19
- But may need refinement: if retrieval scope for a theme is its tag + descendants (theme tag is fixed)
- Cache hit: O(1) lookup from `traversal_cache.subtree_exemplars` or similar
- Returns Python `set` of tag strings

---

**References:** ADR-006 (Retrieval — scope restriction stage)
