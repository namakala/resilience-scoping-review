---
title: "46 — theme-approval-enables-interpretation"
description: "When all themes for a tag subtree approved, mark tag span ready"
updated_at: "2026-05-12"
phase: 7
---

# Feature 46: theme-approval-enables-interpretation


---

## Description

When all themes for a tag subtree are approved (no draft/rejected themes), mark that tag span as "interpretation-ready". Set `dirty_flags[tag] = True` to schedule interpretation inference. Track readiness in `session_state` table: `interpretation_ready_tags` list.

---

## Acceptance Criteria

- After last theme for tag `X` approved, `interpretation_ready_tags` includes `X` and all its ancestor tags (subtree consolidated)
- If a theme is later edited or merged, tag removed from ready list until all themes re-approved
- Interpretation synthesis stage only processes tags in ready list
- Ready status visible in HITL dashboard

---

## Dependencies

@docs/plan/45-theme-constraint-validation.md
@docs/plan/10-session-state-manager.md

---

## Implementation Notes

- Module: `src/python/inference/readiness.py`
- On theme approval, trigger `check_tag_ready(tag)`:
  - Get all codes for tag; group by `code.tag` (codes under tag include descendants from scope? Actually themes per tag not subtree — clarify)
  - Wait, spec says: "When all themes for a tag subtree are approved" — interpretation may span multiple tags; but readiness is per tag. So for a given tag, all its approved themes → that tag is ready. But interpretation requires multiple tags; so readiness accumulates across tags.
  - Track: `session_state['interpretation_ready_tags'] = list of tags ready`
- When all themes under tag `T` have `status='approved'` (exclude `draft`, `rejected`, `merged`), add `T` to ready set
- If any theme under `T` later becomes `draft` (via edit/merge), remove `T` from ready set
- Interpretation synthesis (Feature 47) queries ready tags and pairs contiguous subtrees

---

**References:** ADR-007 (Incremental — readiness propagates to interpretation stage)
