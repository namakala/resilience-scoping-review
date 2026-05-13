---
title: "10 — session-state-manager"
description: "Workflow state persistence: stage, dirty_flags, checkpoint"
updated_at: "2026-05-13"
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
- Table: `session_state(key VARCHAR PRIMARY KEY, value VARCHAR NOT NULL, type VARCHAR NOT NULL)` — matches schema in `duckdb_schema.py` (no `updated_at` column)
- All workflow state stored as a single JSON object under `key='workflow'` with `type='dict'`
- State dict structure: `{"current_stage": 1, "dirty_flags": {}, "last_checkpoint": null, "config_version": "", "user_action_count": 0}`
- Extra keys beyond the five required fields are allowed and preserved (e.g., `interpretation_ready_tags`, `token_usage`)
- Dirty flags: `{"Problem.Cause": true, "Problem.Impact": false}` — stored as nested dict within the workflow JSON
- `save_state()` called after each stage checkpoint; automatically sets `last_checkpoint` to current UTC time if not already set
- `reset_state()` performs a full table wipe (`DELETE FROM session_state`) as specified in plan 64
- Partial field updates (`update_dirty_flag`, `set_current_stage`, `increment_user_action_count`, `set_config_version`, `set_last_checkpoint`) use load-modify-save pattern since DuckDB in this project version lacks `json_set`
- Validation via `validate_state()` rejects invalid stage numbers (must be int 1–10), non-dict dirty_flags, non-string config_version, negative user_action_count; booleans are rejected for int fields to prevent `True`/`False` being treated as `1`/`0`
- `DEFAULT_STATE` uses `copy.deepcopy` on return to prevent mutation of module-level constant

---

## Completion Summary

**Completed:** 2026-05-13

All acceptance criteria satisfied:
- State survives process restart: `save_state` + close + `load_state` returns identical values.
- `dirty_flags` updated atomically per tag via `update_dirty_flag()` (load-modify-save within single connection).
- Checkpoint timestamp (`last_checkpoint`) updated automatically on each `save_state()` call.
- On `--resume`, `load_state()` returns previously saved dict for orchestration to resume.
- `validate_state()` rejects invalid stage numbers, malformed dirty_flags, and other schema violations.
- `reset_state()` clears all rows from `session_state` (full wipe).
