---
title: "21 — constraint-validator"
description: "Enforce ADR-013: one-code-one-theme, single-tag-per-theme, contiguous span"
updated_at: "2026-05-14"
phase: 3
---

# Feature 21: constraint-validator


---

## Description

Enforce ADR-013 structural invariants via `validate_constraint(entity, action)`. Rules: (1) code must belong to exactly one theme upon approval; (2) theme must contain ≥2 codes and all codes share same parent tag; (3) theme must belong to exactly one interpretation upon approval; (4) interpretation may span multiple tags but only contiguous subtree (no gaps); (5) tag assignments must exist in ontology; (6) no cycles introduced through merges.

---

## Acceptance Criteria

- Validator called before every mutation (code approval, theme merge, interpretation creation)
- On violation, raises `ConstraintError` with code and human-readable message (e.g., "CONSTRAINT_VIOLATION_TAG_MISMATCH: Theme 'X' contains codes from multiple tags: [A, B]")
- All six rules covered by unit tests with boundary cases
- Validation functions pure and testable in isolation
- Constraint checking integrates with HITL layer to prevent invalid user actions

---

## Dependencies

@docs/plan/14-node-query-operations.md
@docs/plan/18-ontology-traversal-ops.md

---

## Module Structure

Three-file split (each <160 lines, satisfying STANDARDS.md 300-line limit):

- **`src/python/ontology/constraints.py`** — Public API: error codes, `ConstraintError`,
  `_resolve_graph`/`_resolve_tag_dag` helpers, `validate_constraint()` dispatch.
  Re-exports `is_contiguous_subtree` from `contiguity.py`.

- **`src/python/ontology/rules.py`** — Six rule implementations as public functions
  (`validate_code_approval`, `validate_theme_approval`, etc.) with `__all__` control.
  **Not re-exported** from `__init__.py` — thus not part of the package public API.
  Importable for testing: `from ontology.rules import validate_code_approval`.

- **`src/python/ontology/contiguity.py`** — Standalone contiguous-subtree check:
  `is_contiguous_subtree()`, `_missing_intermediates()`. Shared with Feature 50.
  No imports from sibling ontology modules (lazy imports `dag.get_tag_dag`).

## Import Order (avoids circular dependency)

Error codes + `ConstraintError` are **defined first** in `constraints.py` before the
`from .rules import ...` line. When `rules.py` executes `from .constraints import ...`,
those symbols are already in the partially-initialized module — safe.

## Rule Details

- Rule 1: check on code approval — query theme membership; code already assigned to exactly one theme (enforced at creation time via tag inheritance)
- Rule 2: on theme approval — fetch constituent codes via `composed-of` edges; verify all have same `tag` attribute; count ≥2
- Rule 3: on theme approval — check no other theme in same tag already assigned to an interpretation (one-theme-per-interpretation means each theme belongs to exactly one interpretation, not that interpretation has only one theme — clarify policy)
- Rule 4: on interpretation creation — `is_contiguous_subtree(tag_spans)` (Feature 50)
- Rule 5: when assigning tag to entity, check `tag in ontology_graph`
- Rule 6: after merge, run cycle detection on affected subgraph
- Integrate: call `validate_constraint()` in HITL before persisting action

---

**References:** ADR-013 (Ontology Constraints)
