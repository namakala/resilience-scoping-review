---
title: "61 — hitl-coordination"
description: "Orchestration invokes HITL review; captures actions; updates graph and dirty flags"
updated_at: "2026-05-12"
phase: 10
---

# Feature 61: hitl-coordination


---

## Description

Orchestration invokes HITL review subsystems: `hitl.review_codes(pending_codes)`, `hitl.review_themes(pending_themes)`, `hitl.review_interpretations(pending_interpretations)`. HITL returns list of user actions. Orchestration applies actions to graph (via graph API) and updates dirty flags accordingly.

---

## Acceptance Criteria

- Pending items queried from graph: `status='draft'` and not deferred
- HITL invoked with correct item set; returns actions list
- Each action applied transactionally; graph updated
- After HITL completes, `user_action_count` incremented by action count
- If no pending items, stage auto-advances (nothing to review)

---

## Dependencies

@docs/plan/60-stage-transition-driver.md
@docs/plan/39-code-hitl-cli.md
@docs/plan/44-theme-hitl-cli.md
@docs/plan/49-interpretation-hitl-cli.md

---

## Implementation Notes

- Module: `src/python/orchestration/hitl_coordinator.py`
- For stage 5: `pending_codes = get_nodes_by_type_and_tag('code', status='draft')`; `actions = hitl.review_codes(pending_codes)`; apply each action via `apply_action(action)`
- For stage 7: pending themes; stage 9: pending interpretations
- `apply_action`: switch on `action.type` → call appropriate graph update function (`approve_node`, `edit_node`, `merge_nodes`, `reject_node`)
- After applying, call `set_dirty(tag)` for affected tags from action metadata
- Increment `user_action_count` in `session_state`
- If pending list empty: log "No items to review; auto-advancing"; skip HITL invocation

---

**References:** ADR-011
