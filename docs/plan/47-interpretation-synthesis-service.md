---
title: "47 — interpretation-synthesis-service"
description: "Batch LLM across multiple tags' themes to synthesize cross-cutting interpretations"
updated_at: "2026-05-15"
phase: 8
---

# Feature 47: interpretation-synthesis-service


---

## Description

Given multiple approved themes from distinct tags (tag span must be contiguous subtree), call LLM with `interpretation_synthesis.j2` prompt. Provide: list of themes (name, narrative, tag, code count), hierarchical ontology context (ancestor chain), and tag subtree diagram. Ask LLM to synthesize cross-cutting interpretations. Each interpretation includes: `interpretation_name`, `narrative`, `theme_ids` (list), `key_insights`.

---

## Acceptance Criteria

- Input: themes from ≥2 different tags (contiguous subtree per validation)
- Output: one or more interpretation candidates
- Each interpretation's narrative synthesizes insights across the provided themes (not just summary)
- `theme_ids` all have tag_spans forming a single contiguous subtree (validated pre-flight)
- Service returns list of `InterpretationInference` items
- Rejected if input tags are not contiguous (caught by validator before LLM call)

---

## Dependencies

@docs/plan/46-theme-approval-enables-interpretation.md
@docs/plan/22-scope-restriction-helper.md

---

## Implementation Notes

- Module: `src/python/inference/interpretation_synthesis.py`
- Get ready tags from `session_state['interpretation_ready_tags']`; group contiguous tag spans
- For each contiguous span (≥2 tags), get all approved themes for those tags
- Build prompt context: `tag_hierarchy` diagram (indented tree), list of themes with tag metadata
- Call LLM with `temperature=0.5` (more creative); parse `InterpretationInference` schema
- Pre-flight: `is_contiguous_subtree(set_of_tags)` (Feature 50); if false, skip and log warning
- Post-process: deduplicate interpretation names; flag overlapping interpretations for review

---

**References:** ADR-010
