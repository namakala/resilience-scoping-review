---
title: "44 — theme-hitl-cli"
description: "Rich CLI for theme review: approve/edit/merge/reject/defer"
updated_at: "2026-05-12"
phase: 7
---

# Feature 44: theme-hitl-cli


---

## Description

Interactive CLI for theme review. For each draft theme:
- Display panel: **Theme name**, **Narrative**
- List constituent codes (name + exemplar count) in table
- Show similar existing themes (if any) from `neighbor-discovery-service`
- Prompt: `[A]pprove, [E]dit narrative, [M]erge, [R]eject, [D]efer`

Actions:
- **Approve**: status→`approved`; enables interpretation for tag span if all themes approved
- **Edit**: modify narrative (can add/remove codes via checkboxes); status→`draft`
- **Merge**: select another theme to merge with; combines code sets; source marked `merged`
- **Reject**: status→`rejected`; excluded from interpretation
- **Defer**: keep `draft`

---

## Acceptance Criteria

- UI shows code table with ID, name, exemplar count
- Edit allows code list modification (add/remove codes); constraint: all codes must remain within same parent tag
- Merge preview shows combined code list
- Neighbor list displays up to 3 similar themes with similarity scores
- All actions logged

---

## Dependencies

@docs/plan/43-theme-node-creation.md
@docs/plan/39-code-hitl-cli.md

---

## Implementation Notes

- Module: `src/python/hitl/theme_review.py`
- Get constituent codes: traverse `composed-of` edges from theme node
- Display: `rich.Table` with columns: Code ID, Name, Exemplars
- Neighbors: call `find_neighbors(theme_id, entity_type='theme')`
- Edit narrative: `questionary.text("Edit narrative", default=current_narrative)`
- Edit codes: multi-select `questionary.checkbox("Select codes", choices=codes, default=selected)`
- Merge: select target theme; show side-by-side diff of code lists
- After action, log `user_actions` and update `dirty_flags`

---

**References:** ADR-011
