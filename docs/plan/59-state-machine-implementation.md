---
title: "59 — state-machine-implementation"
description: "WorkflowState tracks stage, dirty_flags, checkpoint, config_version"
updated_at: "2026-05-15"
phase: 10
---

# Feature 59: state-machine-implementation


---

## Description

`WorkflowState` class tracks: `current_stage` (int 1–10), `dirty_flags` (dict tag→bool), `last_checkpoint` (timestamp), `config_version` (str), `user_action_count` (int). State transitions only when dependencies satisfied (e.g., cannot enter theme review without codes approved). State persisted to `session_state` table.

---

## Acceptance Criteria

- Initial state: `current_stage=1` (load), `dirty_flags={}`
- Transition method `advance_stage()` validates prerequisites before incrementing
- Invalid transition (e.g., skip from stage 3 to 5) raises `StateError`
- State serializable to JSON and back
- Equality comparison for testing: `state1 == state2`

---

## Dependencies

@docs/plan/10-session-state-manager.md

---

## Implementation Notes

- Module: `src/python/orchestration/state.py`
- Class `WorkflowState`:
  - `from_json(json_str) -> WorkflowState`
  - `to_json() -> str`
  - `can_advance_to(stage) -> bool` checks prerequisites (stage mapping)
  - `set_dirty(tag)` method
- Prerequisites: cannot skip stages; `stage_prereqs = {2: [1], 3: [2], 4: [3], 5: [4], 6: [5], 7: [6], 8: [7], 9: [8], 10: [9]}`; also check dependent flags? Not needed for linear progression
- `config_version`: hash of config file contents; detect changes on resume
- Load/save via `session_state` manager

---

**References:** None
