---
title: "60 — stage-transition-driver"
description: "Main loop: execute stage → checkpoint → HITL if review → advance"
updated_at: "2026-05-12"
phase: 10
---

# Feature 60: stage-transition-driver


---

## Description

Main loop: execute current stage via DAG; checkpoint state; if stage is review stage, invoke HITL; then advance. Stages: load (1) → embed (2) → index (3) → infer_codes (4) → review_codes (5) → infer_themes (6) → review_themes (7) → infer_interpretations (8) → review_interpretations (9) → export (10). Each stage blocks until complete.

---

## Acceptance Criteria

- Stage 1 loads artifacts; writes checkpoint after completion
- Review stages (5,7,9) block waiting for user input via HITL
- After review, stage advances automatically
- Interrupted stage (Ctrl-C) can be resumed from same stage (not repeated)
- Stage durations logged: `"Stage 4 (infer_codes) completed in 125.3s"`

---

## Dependencies

@docs/plan/59-state-machine-implementation.md
@docs/plan/52-dag-constructor.md

---

## Implementation Notes

- Module: `src/python/orchestration/runner.py`
- `run_pipeline(dag, state, config)`:
  ```python
  while state.current_stage <= 10:
      execute_stage(dag, state.current_stage)
      save_checkpoint(state)
      if state.current_stage in [5,7,9]:
          hitl_coordinate(state)
      state.advance_stage()
  ```
- `execute_stage`: determine which DAG nodes to run for that stage; `dag.execute(inputs, overrides={'stage': state.current_stage})`
- Checkpoint: `save_state(state)` after each stage
- Interrupt: catch `KeyboardInterrupt`; call `save_state`; exit(0)
- Logging: `logger.info("Stage %d (%s) started", stage, stage_name)`; duration logged on finish

---

**References:** None
