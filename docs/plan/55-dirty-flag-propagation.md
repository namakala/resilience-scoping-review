---
title: "55 — dirty-flag-propagation"
description: "When node output changes, set dirty_flags for downstream branches"
updated_at: "2026-05-15"
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

---

## Completion Summary

**Completed:** 2026-05-15

All acceptance criteria satisfied:

- **Edit propagation verified:** `propagate_dirty(con, tag)` marks the tag and all its ontology ancestors dirty — code → theme → interpretation cascade tested via ontology DAG traversal.
- **DAG dependency respect:** Ancestors are marked dirty; sibling/non-ancestor tags are not. Verified with 3-level ontology DAG test.
- **`session_state.dirty_flags` accuracy:** `propagate_dirty` writes through `update_dirty_flag()` (load-modify-save), verified via persistence roundtrip tests.
- **Clean nodes served from cache:** `infer_codes`/`infer_themes`/`infer_interpretations` skip batches whose tag is not dirty (when `dirty_flags` dict is provided). Verified via mock LLM call count — clean batches produce zero calls.
- **Selective recomputation verified:** With 3 batches (A=dirty, B=clean, C=dirty), only 2 Groq calls are made, not 3. Verified via `test_infer_codes_mixed_dirty_clean`.

### Files Created
- `src/python/pipeline/dirty.py` — propagation, set, clear, is_dirty, any_tag_dirty
- `tests/unit/pipeline/dirty_test.py` — 21 tests covering all propagation paths

### Files Modified
- `src/python/pipeline/wiring.py` — added `dirty_flags` to `EXTERNAL_INPUTS`
- `src/python/pipeline/nodes/inference_nodes.py` — added `dirty_flags` param with per-tag skip logic to `infer_codes`, `infer_themes`, `infer_interpretations`
- `src/python/hitl/invalidation.py` — replaced `update_dirty_flag` calls with `propagate_dirty` for upward propagation
- `tests/unit/pipeline/inference_nodes_test.py` — added 7 dirty flag tests
- `tests/unit/pipeline/dag_constructor_test.py` — added `dirty_flags` to external_inputs exclusion set
- `docs/plan/55-dirty-flag-propagation.md` — this completion summary
- `PLANS.md` — marked Feature 55 complete
- `AGENTS.md` — documented dirty.py module

### Test Results
- **1074 unit tests pass** (21 new dirty.py tests + 7 new dirty-flag inference tests + 1046 existing tests with 0 regressions)
