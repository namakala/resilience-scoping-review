---
title: "40 — code-merge-action"
description: "Merge two codes; redirect edges; invalidate downstream caches"
updated_at: "2026-05-14"
phase: 6
---

# Feature 40: code-merge-action


---

## Description

Implement merge logic: given two code node IDs, merge into target (survivor). Redirect all `contains` edges from source to target. Mark source node `status='merged'` and add `merged_into` property. Create `derived-from` edge: source → target. Invalidate downstream caches: if either code participated in a theme, that theme marked `draft`; if that theme in interpretation, interpretation marked `draft`.

---

## Acceptance Criteria

- Merge operation atomic via transaction
- After merge, querying by tag returns only survivor code
- `derived-from` chain preserves lineage (source → target)
- Downstream dirty flags set: theme status→draft if it contained merged code; interpretation status→draft if it contained that theme
- Merge audited in `user_actions` with `action_type='merge'`
- Cannot merge codes of different types (code+theme rejected by validator)

---

## Dependencies

@docs/plan/39-code-hitl-cli.md
@docs/plan/21-constraint-validator.md

---

## Implementation Notes

- Module: `src/python/hitl/merge.py`
- SQL: `UPDATE nodes SET status='merged', data_json=data_json || {'merged_into': target_id} WHERE id=?`
- Redirect edges: `UPDATE edges SET source_id=? WHERE source_id=? AND edge_type='contains'` (or delete old + insert new)
- Create `derived-from` edge: source (old) → target (survivor)
- Invalidate: update theme status to `draft` for themes containing target; cascade to interpretations
- Transaction: all steps within `graph_transaction()`
- Log: `INSERT INTO user_actions (action_type, entity_id, old_value, new_value) VALUES ('merge', source_id, ...)`

---

**References:** ADR-011
