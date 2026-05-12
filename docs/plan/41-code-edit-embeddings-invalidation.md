---
title: "41 — code-edit-embeddings-invalidation"
description: "Editing code definition invalidates embedding and sets dirty flag"
updated_at: "2026-05-12"
phase: 6
---

# Feature 41: code-edit-embeddings-invalidation


---

## Description

When user edits code definition, update node `definition` field, set `status='draft'`, and mark code's embedding as stale. Invalidation: delete row from `embedding_cache` where `entity_id=code_id` and `entity_type='code'`. Dirty flag set for that code's tag branch, triggering re-embedding on next pipeline run.

---

## Acceptance Criteria

- Edit via HITL CLI calls this invalidation automatically
- Embedding cache entry removed; subsequent retrieval triggers regeneration
- `session_state.dirty_flags[tag] = True` set
- Re-running pipeline regenerates embedding for edited code only (incremental)
- Edit action logged with `old_value` and `new_value` in `user_actions`

---

## Dependencies

@docs/plan/39-code-hitl-cli.md
@docs/plan/08-embedding-cache-schema.md
@docs/plan/10-session-state-manager.md

---

## Implementation Notes

- Module: `src/python/hitl/edits.py`
- Function: `invalidate_code_embedding(code_id: int, tag: str)`
- SQL: `DELETE FROM embedding_cache WHERE entity_id=? AND entity_type='code'`
- Dirty flag: `UPDATE session_state SET value=json_set(value, '$.dirty_flags."<tag>"', true) WHERE key='workflow'`
- Called from code review CLI after edit action
- Also invalidate if code is merged (source removed, target updated)

---

**References:** ADR-005 (Embedding immutability/mutability), ADR-007
