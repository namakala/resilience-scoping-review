---
title: "18 — ontology-traversal-ops"
description: "get_ancestors, get_descendants, get_subtree, is_ancestor"
updated_at: "2026-05-12"
phase: 3
---

# Feature 18: ontology-traversal-ops


---

## Description

Implement tag traversal functions: `get_ancestors(tag: str) → list[str]` (all parents up to root, ordered root→parent), `get_descendants(tag: str) → list[str]` (all children down to leaves, depth-first), `get_subtree(tag: str) → set[str]` (tag + all descendants), `is_ancestor(parent: str, child: str) → bool`.

---

## Acceptance Criteria

- `get_ancestors('Problem.Cause.Scope')` returns `['Problem', 'Problem.Cause']`
- `get_descendants('Problem')` returns all tags under Problem in any order (sorted by depth)
- `get_subtree` includes the input tag itself
- `is_ancestor` uses cached ancestor sets for O(1) lookup
- Functions raise `KeyError` for unknown tag
- Performance: `get_descendants` on root with 1000 tags <50ms (cached)

---

## Dependencies

@docs/plan/17-tag-dag-construction.md

---

## Implementation Notes

- Module: `src/python/ontology/traversal.py`
- Use precomputed caches from Feature 19: `get_cached_ancestors(tag)`, `get_cached_descendants(tag)`
- `get_ancestors`: from cache list, filter to ancestors only (exclude self and siblings)
- `get_subtree = {tag} ∪ get_descendants(tag)`
- `is_ancestor`: `parent in get_ancestors(child)`
- Cache warm-up at system initialization

---

**References:** ADR-003, ADR-012 (Traversal Caching)
