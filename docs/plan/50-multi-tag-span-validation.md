---
title: "50 — multi-tag-span-validation"
description: "Ensure interpretation tag_spans form a contiguous subtree (LCA-based)"
updated_at: "2026-05-12"
phase: 8
---

# Feature 50: multi-tag-span-validation


---

## Description

Ensure interpretation's `tag_spans` form a contiguous subtree (connected in ontology DAG). Compute using LCA (lowest common ancestor): all tags must share a single root ancestor, and no intervening tags missing from span. If gap detected (e.g., tags A and C but not B where B is ancestor of C and descendant of A), reject.

---

## Acceptance Criteria

- Validation runs before interpretation node creation (pre-flight) and before approval
- `is_contiguous_subtree(tag_set)` returns True if tags form connected subtree
- Counter-example: tags = {`Problem`, `Problem.Cause`, `Problem.Impact`} → contiguous (all under Problem)
- Counter-example: tags = {`Problem.Cause`, `Problem.Impact`} → non-contiguous if `Problem` not included (LCA is Problem; but children only without parent may be considered contiguous depending on policy—policy documented)
- Rejection message: "CONSTRAINT_NONCONTIGUOUS_SPAN: Tags X and Y are not connected in ontology. Include bridging tag Z."
- Integrated into HITL: split action automatically ensures contiguity

---

## Dependencies

@docs/plan/21-constraint-validator.md
@docs/plan/49-interpretation-hitl-cli.md

---

## Implementation Notes

- Module: `src/python/ontology/constraints.py` (same file as Feature 21)
- `is_contiguous_subtree(tags: set[str]) → bool`:
  1. Get all pairwise LCAs? Simpler: compute union of all paths from tags to root
  2. The set should form a connected subtree: for any two tags in set, all nodes on shortest path between them in ontology DAG should also be in set
  3. Alternative: check that `get_subtree(lca_tag)` contains all tags and no tag outside set lies on path between any two; but that's complex
  4. Simplify: tags contiguous if the induced subgraph is connected when edges are `parent-child` restricted to tags in set plus their LCA. Policy: allow grandchildren without parent? The spec says "contiguous subtree only" — typically means a connected subgraph of the DAG that is downward-closed? Actually a subtree rooted at some tag: either all tags in set are descendants of some root tag R, and every tag on path from R to any tag in set is also in set (downward-closed). So: find minimal enclosing tag (LCA of all tags). Then verify that every tag on path from LCA to each tag is also in set. If any missing → non-contiguous.
- Implementation: `lca = lowest_common_ancestor(tags)`; for each tag, get path `lca → tag` (excluding lca); require all intermediate nodes in set
- Called in `validate_constraint()` for interpretation approval and creation
- Split action in HITL automatically assigns themes to new interpretations such that each interpretation's tag_spans are contiguous (by splitting along tag boundaries)

---

**References:** ADR-013
