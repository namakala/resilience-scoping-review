---
title: "64 — session-resume-logic"
description: "On --resume, load state; skip completed stages; start from checkpoint"
updated_at: "2026-05-12"
phase: 10
---

# Feature 64: session-resume-logic


---

## Description

On `--resume` flag, orchestration loads `session_state` from DuckDB. Reads `current_stage`, `dirty_flags`, `config_version`. If config version mismatches, prompts user to restart or override. Skips all completed stages; starts from `current_stage` checkpoint.

---

## Acceptance Criteria

- Resume after crash: stage 4 interrupted → `--resume` starts at stage 4 (not stage 1)
- State includes `dirty_flags` so selective recomputation correct
- Config version check: if `config_hash` changed, warn and require `--force-resume`
- Cleared state on explicit `--reset` flag
- Log message: `"Resuming from stage N (checkpoint at T)"`

---

## Dependencies

@docs/plan/59-state-machine-implementation.md
@docs/plan/60-stage-transition-driver.md

---

## Implementation Notes

- Module: `src/python/orchestration/resume.py`
- In `main()`, if `--resume`: `state = load_state()`; else `state = WorkflowState.initial()`
- Config version: compute `hashlib.sha256(open(config).read().encode()).hexdigest()[:16]`; compare to `state.config_version`; if mismatch and not `--force-resume`, print error and exit(2)
- Reset: `--reset` clears `session_state` table; restarts from stage 1
- Logging: `logger.info("Resuming from stage %d (checkpoint %s)", state.current_stage, state.last_checkpoint)`

---

**References:** None
