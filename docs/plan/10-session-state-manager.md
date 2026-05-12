---
title: "10 — session-state-manager"
description: "Workflow state persistence: stage, dirty_flags, checkpoint"
updated_at: "2026-05-12"
phase: 1
---

# Feature 10: session-state-manager


---

## Description

Implement state persistence in `session_state` table. Manage keys: `current_stage` (int 1–10), `dirty_flags` (JSON mapping tag→bool), `last_checkpoint` (timestamp), `config_version` (str), `user_action_count` (int). Provide `save_state()`, `load_state()`, `reset_state()` functions.

---

## Acceptance Criteria

- State survives process restart (write then read returns same values)
- `dirty_flags` can be updated atomically per tag
- Checkpoint created after each stage completion (timestamp updated)
- On `--resume`, state loaded automatically before stage execution
- State validation rejects invalid stage numbers or malformed JSON

---

## Dependencies

@docs/plan/07-duckdb-schema-init.md

---

## Implementation Notes

- Module: `src/python/persistence/state.py`
- Table: `session_state(key TEXT PRIMARY KEY, value TEXT, updated_at TIMESTAMP)`
- Store as JSON: `json.dumps(dict)` → TEXT; read back with `json.loads()`
- Dirty flags: `{"Problem.Cause": true, "Problem.Impact": false}`
- `save_state()` called after each stage checkpoint

---

**References:** ADR-007 (Incremental Evolution)
