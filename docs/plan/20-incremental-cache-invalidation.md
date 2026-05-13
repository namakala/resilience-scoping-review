---
title: "20 — incremental-cache-invalidation"
description: "Mark cache rows stale; lazy recompute on next access"
updated_at: "2026-05-14"
phase: 3
---

# Feature 20: incremental-cache-invalidation


---

## Description

When ontology mutates (e.g., tag merge, new tag addition), invalidate cache only for affected tags. Implement `invalidate_cache_for_tag(tag)` marking cache rows as stale; background job recomputes in lazy fashion on next access.

---

## Acceptance Criteria

- `invalidate_cache_for_tag('Problem.Cause')` marks that row with `stale=True`
- On next `get_cached_subtree('Problem.Cause')`, if stale, recompute and update row
- Invalidation propagates to all descendants (they depend on parent's ancestor list)
- Bulk invalidation for multiple tags runs in single transaction
- Audit log records invalidation events (timestamp, tag, reason)

---

## Dependencies

@docs/plan/19-traversal-cache-materialization.md

---

## Implementation Notes

- Module: `src/python/ontology/invalidation.py`
- SQL: `UPDATE traversal_cache SET stale=TRUE WHERE tag = ?`
- On cache access: `if stale: recompute() → UPDATE ... SET stale=FALSE`
- Propagation: for descendants, also set stale=True (their ancestor list changed)
- Audit: insert into `invalidation_log(tag, reason, timestamp)` table

---

**References:** ADR-012, ADR-007 (Incremental Evolution)
