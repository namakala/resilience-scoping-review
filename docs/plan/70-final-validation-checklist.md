---
title: "70 — final-validation-checklist"
description: "Verify all ADR requirements implemented; sign-off"
updated_at: "2026-05-12"
phase: 11
---

# Feature 70: final-validation-checklist


---

## Description

Verify all ADR requirements implemented:
- ADR-002 (immutability): exemplars, keywords, tags never regenerated without invalidation
- ADR-005 (embedding policy): exemplar/keyword immutable; code/theme/interpretation mutable; embeddings recompute on content change
- ADR-006 (retrieval): hybrid (BM25+cosine+proximity); scope→BM25→embeddings→fusion
- ADR-007 (incremental): dirty-state propagation; selective recomputation
- ADR-010 (LLM): batch by tag; JSON structured; Groq; retry logic
- ADR-011 (HITL): approve/edit/merge/reject/defer; atomic mutations; undo/redo
- ADR-012 (caches): traversal caches materialized; incremental invalidation
- ADR-013 (constraints): one-code-one-theme, single-tag-per-theme, contiguous span for interpretation

---

## Acceptance Criteria

- Each ADR verified with at least one integration test demonstrating behavior
- Checklist table in `docs/validation/adr-checklist.md` (created) marks each ADR satisfied
- Researcher sign-off obtained (documented in `docs/validation/signoff.md`)
- Any deviations from ADR documented with rationale
- System considered production-ready per researcher definition

---

## Dependencies

@docs/plan/65-end-to-end-workflow-test.md

---

## Implementation Notes

- Module: `docs/validation/adr-checklist.md` (new file)
- For each ADR, list:
  - Requirement summary
  - Feature(s) that implement it (e.g., "ADR-005 → Features 24,25,41")
  - Test name that verifies it (e.g., `tests/integration/test_embedding_immutability.py`)
  - Status: ✅ Implemented / ⚠️ Partial / ❌ Missing
- `signoff.md`: researcher name, date, "I have reviewed the system against ADRs and confirm it meets requirements."
- Deviations: documented as `deviations.md` with ADR-###, description, rationale, impact
- CI job `validate-adrs` runs checklist and fails if any ADR missing

---

**References:** ADR.md (all)
