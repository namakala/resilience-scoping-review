---
title: "39 — code-hitl-cli"
description: "Rich + questionary CLI for code review: approve/edit/merge/reject/defer"
updated_at: "2026-05-12"
phase: 6
---

# Feature 39: code-hitl-cli


---

## Description

Interactive CLI using `rich` and `questionary`. For each pending code (draft status):
- Display panel: **Code name**, **Definition**, **Supporting quote** (truncated to 100 chars)
- Expandable section: full source exemplar content
- List of semantic neighbor codes (from `neighbor-discovery-service`) with similarity scores
- Prompt: `[A]pprove, [E]dit, [M]erge, [R]eject, [D]efer, [S]kip → More`

Actions:
- **Approve**: status→`approved`; triggers theme inference readiness check
- **Edit**: opens editor (via `$EDITOR` or inline questionary); updates definition; status→`draft`; invalidates embedding
- **Merge**: select another code to merge with; combines exemplar sets; marks source as `merged`; creates `derived-from` link
- **Reject**: status→`rejected`; excluded from downstream
- **Defer**: keep `draft`; skip for now (will reappear later)

---

## Acceptance Criteria

- UI renders correctly in 80x24 terminal
- All five actions functional; selections logged to `user_actions` table
- Edit action validates non-empty definition
- Merge action shows diff preview before confirmation
- Neighbor list helpful (≥1 neighbor shown if exists)
- Session can be interrupted (Ctrl-C) and resumed; pending items remembered
- Unit test: simulate user input sequence via `questionary` mock

---

## Dependencies

@docs/plan/29-neighbor-discovery-service.md
@docs/plan/38-code-node-creation.md

---

## Implementation Notes

- Module: `src/python/hitl/code_review.py`
- Use `rich.panel.Panel`, `rich.table.Table`, `questionary.select`, `questionary.text`
- Neighbor display: `Table` with columns: `Neighbor ID`, `Name`, `Similarity`
- Edit: `questionary.text("Edit definition", default=current_def)`
- Merge: ` questionary.select("Select code to merge with:", choices=code_list)`; show diff via `difflib.unified_diff`
- Defer: skip; code remains draft; appears again next review session
- Actions logged: `user_action_log` table with `action_type`, `entity_id`, `old_value`, `new_value`, `timestamp`

---

**References:** ADR-011 (HITL Validation)
