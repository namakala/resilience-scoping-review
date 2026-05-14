---
title: "42 — theme-inference-service"
description: "Batch LLM call per tag to group approved codes into themes"
updated_at: "2026-05-14"
phase: 7
---

# Feature 42: theme-inference-service


---

## Description

For each tag with approved codes, batch codes (≤5 per theme) to LLM with theme prompt; output `ThemeInference`. Input: all `approved` codes for a given tag. Group codes into themes such that each theme contains 2–5 codes. LLM assigns each code to exactly one theme (no overlap).

---

## Acceptance Criteria

- Every approved code assigned to a theme candidate
- Themes contain 2–5 codes each; if odd number remains, one theme may have 1 code (flagged for review)
- All codes in a theme share same parent tag (pre-flight check before LLM call)
- Service returns list of `ThemeInference` items with `theme_name`, `narrative`, `code_ids`
- Prevents duplicate theme names within same tag (dedup in post-processing)
- Logging: tag-wise summary: `"Tag 'Problem.Cause': 12 codes → 3 themes"`

---

## Dependencies

@docs/plan/37-code-inference-service.md
@docs/plan/22-scope-restriction-helper.md

---

## Implementation Notes

- Entry point: `src/python/inference/theme_inference.py` — `infer_themes(con, tag)`
- Data loading: `src/python/inference/theme_code_loading.py` — `load_approved_codes()`, `load_approved_codes_grouped()`
- Post-processing: `src/python/inference/theme_postprocess.py` — `dedup_theme_names()`, `flag_small_themes()`, `validate_code_belonging()`
- Node creation: `src/python/inference/create_theme_nodes.py` — `create_theme_nodes(con, themes, tag)`
- Fetch approved codes: `codes = get_nodes_by_type_and_tag('code', tag)` filter `status='approved'`
- Group into batches of ≤5 codes per theme; may generate multiple themes per tag
- Prompt: `theme_inference.j2` with context: `{"tag": tag, "codes": [{"id":..., "name":..., "definition":...}]}`
- Call LLM with temperature=0.4; parse `ThemeInference` schema
- Post-process: flag any theme with <2 codes; dedup similar theme names
- Update `inference_status` for codes as `generated` (entity_type=code, stage=theme)

---

**References:** ADR-010
