---
title: "45 — theme-constraint-validation"
description: "Block approval if codes span multiple tags or <2 codes"
updated_at: "2026-05-12"
phase: 7
---

# Feature 45: theme-constraint-validation


---

## Description

Before approving a theme, validate: (1) ≥2 codes assigned, (2) all codes share same parent tag, (3) no duplicate codes. If violated, reject approval and display error message with remediation suggestion. Integrated into `code-hitl-cli` and `theme-hitl-cli` as pre-action check.

---

## Acceptance Criteria

- Approval blocked if codes span multiple tags; error: "CONSTRAINT_TAG_MISMATCH: Theme 'X' contains codes from multiple tags: [A, B]. All codes must belong to the same tag."
- Approval blocked if <2 codes; error: "CONSTRAINT_MIN_CODES: Theme requires at least 2 codes; got N."
- Edit action that removes codes triggers same validation on subsequent approval attempt
- Merge of two themes with different tags rejected
- Constraint errors logged with `constraint_type` code for audit

---

## Dependencies

@docs/plan/44-theme-hitl-cli.md
@docs/plan/21-constraint-validator.md

---

## Implementation Notes

- Module: `src/python/ontology/constraints.py` (same as Feature 21 but called in theme flow)
- In `approve_theme(theme_id)` function:
  1. Fetch theme node; get constituent code_ids via `composed-of` edges
  2. Fetch each code's `tag` attribute; collect unique tags
  3. If len(unique_tags) > 1 → raise `ConstraintError("TAG_MISMATCH", f"Theme contains codes from tags: {unique_tags}")`
  4. If len(code_ids) < 2 → raise `ConstraintError("MIN_CODES", ...)`
- In `theme-hitl-cli`, call validator before executing approve action; catch error and display to user
- Same validator used in theme-inference-service (Feature 42) to pre-filter LLM output; but HITL is final gate

---

**References:** ADR-013
