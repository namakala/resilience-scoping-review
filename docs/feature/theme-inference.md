---
title: "Theme Inference"
description: "Batch LLM inference that groups approved codes into themes per ontology tag, with post-processing validation and status tracking"
updated_at: 2026-05-14
---

# Theme Inference

Groups approved code nodes into thematic clusters via constrained LLM reasoning. One tag at a time, batches of ≤5 codes produce one or more `ThemeInference` objects. Feeds the interpretation synthesis stage downstream.

## Purpose & Design Rationale

Themes are the intermediate abstraction between granular codes (per-exemplar evidence) and cross-cutting interpretations. Each theme aggregates 2–5 related codes within the same ontology tag, producing a descriptive name, narrative, and explicit code-id references. ADR-010 governs the constrained LLM approach: the model receives ontology context (tag path, description, existing codework) and is instructed to output `{"themes": [{theme_name, narrative, code_ids}]}` JSON — the model groups, never edits code content.

**Single-tag constraint:** Codes from different tags never mix in one batch. The ontology hierarchy guarantees that each theme belongs to exactly one tag, preserving the tag→theme→interpretation lineage. Aggregation across tags happens only at the interpretation stage.

## Entry Point

```python
from inference.theme_inference import infer_themes
themes = infer_themes(con, tag="Problem.Cause")  # or None for all tags
```

## Pipeline Flow

1. **Load approved codes:** `load_approved_codes_grouped(con, tag)` queries the graph for all code nodes with status `approved` and groups them by tag. Returns `dict[str, list[_CodeRow]]`.

2. **Batch by tag:** `group_by_tag(codes, max_per_batch=5)` partitions codes into deterministic batches sorted by id. Batches carry a `batch_id` like `theme_Problem.Cause_batch_00`.

3. **Render prompt per batch:** Each batch renders `render_theme_prompt()` using Jinja2 templates (`theme_inference_system.j2` + `theme_inference_user.j2`):
   - Tag description and ontology path (ancestors + self)
   - Code dicts with id, name, definition, exemplar_count
   - Optional few-shot demonstrations loaded from `fewshot/theme_inference.json`

4. **Call Groq:** `infer_batch_with_retry()` with configurable temperature (env `THEME_TEMPERATURE`, default 0.4). Three-tier retry: network exponential backoff → 429 sleep → token-limit batch splitting.

5. **Parse response:** `parse_theme_response()` strips fences, JSON-parses, unwraps from `"themes"` key, validates against `ThemeInference` Pydantic model.

6. **Post-process:**
   - `dedup_theme_names()` — appends `_1`, `_2` on name collision
   - `flag_small_themes()` — warns on themes with <2 codes
   - `validate_code_belonging()` — logs if any code_id falls outside the batch

7. **Update status:** Each code entity transitions to `generated` (stage=theme). Codes not assigned to any theme get `mark_failure`.

## Status Integration

Theme inference reads from the `inference_status` table where `entity_type=code` and `stage=theme`. Only codes with `status=approved` in the code stage are loaded. After inference, codes transition to `generated` (theme stage). HITL review then approves, edits, or rejects each theme. Once all themes in a tag's subtree are approved, the tag becomes "interpretation-ready" (see `readiness.py`).

## Output Schema

```python
class ThemeInference(BaseModel):
    theme_name: str      # LLM-generated descriptive name
    narrative: str        # Human-readable explanation
    code_ids: list[str]   # IDs of codes grouped under this theme
```

## File Map

`theme_inference.py` — entry point + per-batch callback. `theme_code_loading.py` — approved code queries. `theme_postprocess.py` — dedup, size flagging, ID validation. `theme_node_reinfer.py` — draft re-inference support. `templates/theme_inference_system.j2` + `theme_inference_user.j2` — Jinja2 prompt templates. `fewshot/theme_inference.json` — curated examples.

## Dependencies

Relies on graph layer for code node queries, ontology layer for tag metadata (path, description), batch_processor for shared batch loop, groq_client for LLM calls, and status_updates for inference lifecycle tracking.

## References

Implements ADR-010 (LLM Inference). See `@ADR.md` and `@docs/feature/inference-layer.md`. Output feeds interpretation synthesis (`@docs/feature/interpretation-synthesis.md`).
