---
title: "55 — dirty-flag-propagation"
description: "When node output changes, set dirty_flags for downstream branches"
updated_at: "2026-05-12"
phase: 9
---

# Feature 55: dirty-flag-propagation


---

## Description

When a node's output changes (e.g., code edit), set `dirty_flags[tag] = True` in session state. DAG marks dependent nodes (e.g., theme inference for that tag, interpretation synthesis for that tag's subtree) as stale. Next execution skips clean nodes (cached), recomputes dirty ones.

---

## Acceptance Criteria

- Edit to code definition triggers: code node dirty → its theme node dirty → interpretation nodes dirty
- Dirty flag propagation respects DAG dependencies (tested via mock state change)
- `session_state.dirty_flags` JSON accurately reflects branches needing recompute
- Clean nodes served from cache without re-execution
- Selective recomputation verified: edited 1 code out of 100 → only 1 theme recomputed, not all themes

---

## Dependencies

@docs/plan/54-dependency-wiring.md
@docs/plan/10-session-state-manager.md

---

## Implementation Notes

- Module: `src/python/pipeline/dirty.py`
- HITL actions call `set_dirty(tag)` function; this updates `session_state.dirty_flags`
- DAG nodes check `is_dirty(node)` before execution; if clean and cached, skip
- Hamilton has built-in caching; combine with custom dirty flags using `@cachable` with custom `cache_key` that includes dirty flag hash
- Propagation: not automatic DAG-level; we set flags on tags, and nodes check: `if tag in dirty_flags: recompute`
- Alternative: use Hamilton's `@cachable` invalidation by inputs; pass dirty flags as inputs to downstream nodes

---

**References:** ADR-007
