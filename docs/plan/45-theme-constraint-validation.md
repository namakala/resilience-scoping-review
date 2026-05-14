---
title: "45 — theme-constraint-validation"
description: "Block approval if codes span multiple tags or <2 codes"
updated_at: "2026-05-14"
phase: 7
status: completed
---

# Feature 45: theme-constraint-validation

## Description

Before approving a theme, validate: (1) ≥2 codes assigned, (2) all codes share same parent tag, (3) no duplicate codes. If violated, reject approval and display error message with remediation suggestion. Integrated into `code-hitl-cli` and `theme-hitl-cli` as pre-action check.

---

## Acceptance Criteria

- Approval blocked if codes span multiple tags; error: "CONSTRAINT_TAG_MISMATCH: Theme 'X' contains codes from multiple tags: [A, B]. All codes must belong to the same tag." ✓
- Approval blocked if <2 codes; error: "CONSTRAINT_MIN_CODES: Theme requires at least 2 codes; got N." ✓
- Edit action that removes codes triggers same validation on subsequent approval attempt ✓
- Merge of two themes with different tags rejected ✓
- Constraint errors logged with `constraint_type` code for audit ✓

---

## Dependencies

@docs/plan/44-theme-hitl-cli.md
@docs/plan/21-constraint-validator.md

---

## Files Modified

| File | Change |
|---|---|
| `src/python/hitl/theme_review_merge.py` | Added tag-mismatch check before merge; raises `CONSTRAINT_TAG_MISMATCH` when source and target tags differ |
| `src/python/hitl/theme_review_actions.py` | Added `constraint_type=exc.code` to logger `extra` dict for structured audit logging |
| `src/python/hitl/code_review_actions.py` | Added `validate_constraint()` call to `handle_approve()` — closes Feature 21 integration gap for code approval constraint checks |

## Files Created

None. All changes were modifications to existing files.

## Tests

| File | Tests Added |
|---|---|
| `tests/unit/hitl/theme_review_test.py` | `test_approve_logs_constraint_type`, `test_merge_themes_different_tags_rejected` |
| `tests/unit/hitl/code_review_actions_test.py` | `test_approve_fails_constraint_validator` |

**Test result:** 834 passed, 0 failed (no regressions)

---

**References:** ADR-013
