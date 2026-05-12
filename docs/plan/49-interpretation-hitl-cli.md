---
title: "49 — interpretation-hitl-cli"
description: "Rich CLI for interpretation review: approve/edit/split/reject/defer"
updated_at: "2026-05-12"
phase: 8
---

# Feature 49: interpretation-hitl-cli


---

## Description

Interactive CLI for interpretation review. For each draft interpretation:
- Display panel: **Interpretation name**, **Narrative**
- List constituent themes with tag context (e.g., "Theme X [tag: Problem.Cause]")
- Show full evidence chain (expandable: interpretations → themes → codes → exemplar quotes)
- Prompt: `[A]pprove, [E]dit narrative, [S]plit, [R]eject, [D]efer`

Actions:
- **Approve**: status→`approved`; finalizes interpretation
- **Edit**: modify narrative; status→`draft`; embedding invalidated
- **Split**: break interpretation into two by selecting subset of themes; creates two new interpretation nodes; original marked `merged`
- **Reject**: status→`rejected`; excluded from final output
- **Defer**: keep `draft`

---

## Acceptance Criteria

- Split action produces ≥2 new interpretations; each has contiguous tag span validated
- Evidence chain display indented hierarchically; expandable details
- Edit preserves tag_spans (cannot change scope via edit)
- Neighbor interpretations shown (if any) for context
- All actions logged

---

## Dependencies

@docs/plan/48-interpretation-node-creation.md
@docs/plan/39-code-hitl-cli.md

---

## Implementation Notes

- Module: `src/python/hitl/interpretation_review.py`
- Evidence chain: for each theme → traverse `composed-of` to codes → traverse `contains` to exemplars; display small excerpt
- Hierarchical display: use `rich.tree.Tree` or indented panels
- Split: multi-select themes to assign to new interpretation; second new interpretation gets remaining themes; both must have contiguous spans validated (Feature 50)
- Edit: `questionary.text("Edit narrative", default=current_narrative)`
- Neighbors: `find_neighbors(interpretation_id, entity_type='interpretation')`
- After split, original interpretation status=`merged`; two new interpretations `draft`

---

**References:** ADR-011
