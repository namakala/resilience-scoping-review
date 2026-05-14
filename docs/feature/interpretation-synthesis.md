---
title: "Interpretation Synthesis"
description: "Batch LLM synthesis that generates cross-cutting interpretations from approved themes across contiguous ontology tag spans"
updated_at: 2026-05-14
---

# Interpretation Synthesis

Synthesizes cross-cutting interpretations from approved themes. Operates on contiguous ontology subtrees (≥2 tags), not single tags. Each interpretation aggregates multiple themes across different tags, producing a narrative, key insights, and explicit theme-id references.

## Purpose & Design Rationale

Interpretations are the highest-level semantic artifact in the pipeline. While codes capture per-exemplar evidence and themes aggregate codes within one tag, interpretations synthesize across tags — revealing connections between distinct branches of the ontology (e.g., linking "Problem.Cause" themes with "Coping.Strategy" themes). This is the "so what" stage: the LLM acts as a research synthesizer, identifying cross-cutting patterns that a single-tag view would miss.

**Subtree constraint:** Only contiguous tag subtrees are processed together. Two tags that are not connected in the ontology DAG cannot be synthesized in one interpretation. This preserves hierarchical coherence — interpretations emerge from structurally related concepts.

## Readiness Prerequisite

A tag is "interpretation-ready" when ALL themes in its entire subtree (tag + descendants via `get_subtree`) are approved — no draft or rejected themes remain. The readiness subsystem (`readiness.py`) manages this lifecycle:

- `check_tag_ready(con, tag)` — queries all descendant theme statuses; adds tag + ancestors to `session_state['interpretation_ready_tags']` on success
- `get_ready_tags(con)` — returns the accumulated ready list
- `remove_tag_from_ready(con, tag)` — called when a theme edit or rejection invalidates readiness (dirty-state propagation)

## Entry Point

```python
from inference.interpretation_synthesis import synthesize_interpretations
interps = synthesize_interpretations(con)  # or tag="Problem" for single-tag filter
```

## Pipeline Flow

1. **Discover ready tags:** `get_ready_tags(con)` loads from `session_state['interpretation_ready_tags']`. If a single `tag` arg is provided, filters to only that tag.

2. **Group into spans:** `group_ready_tags_into_spans(ready_tags)` partitions the set into weakly connected components of the ontology DAG induced subgraph. Each component must pass `is_contiguous_subtree()` validation. Components with <2 tags are discarded.

3. **Build batches:** `build_interpretation_batches(spans)` converts each span into one `Batch` containing a single `_InterpretationSpanItem`. Pre-loads approved themes via `load_approved_themes_grouped(span)`. Spans with zero approved themes are skipped.

4. **Render prompt per span:** `render_interpretation_prompt()` uses Jinja2 templates (`interpretation_synthesis_system.j2` + `interpretation_synthesis_user.j2`) with:
   - `build_tag_hierarchy(span_tags)` — ancestry paths per tag
   - `build_ontology_subtree(span_tags)` — indented subtree diagram
   - `themes_by_tag` dict — themes grouped by their parent tag
   - Optional few-shot demonstrations from `fewshot/interpretation_synthesis.json`

5. **Call Groq:** `infer_batch_with_retry()` with configurable temperature (env `INTERPRETATION_TEMPERATURE`). Same three-tier retry as other inference stages.

6. **Parse response:** `parse_interpretation_response()` extracts from `"interpretations"` key, validates against `InterpretationInference` Pydantic model.

7. **Post-process:**
   - `dedup_interpretation_names()` — appends `_1`, `_2` on collision
   - `flag_overlapping_themes()` — warns if a theme appears in multiple interpretations
   - `validate_theme_ids_exist()` — LLM hallucination detection (theme ID not in span)

8. **Update status:** Each theme across all tags in the span gets `mark_success(con, theme.id, type=theme, stage=interpretation)`.

## Output Schema

```python
class InterpretationInference(BaseModel):
    interpretation_name: str   # Synthesized cross-cutting name
    narrative: str              # Full narrative description
    theme_ids: list[str]        # Theme IDs from across tags
    key_insights: list[str]     # 2-5 bullet-point insights
```

## File Map

`interpretation_synthesis.py` — entry point and span-level orchestration. `interpretation_span_grouping.py` — pure DAG functions for span detection, hierarchy, subtree. `interpretation_batch_builder.py` — Batch object construction with pre-loaded themes. `interpretation_span_processor.py` — per-span LLM callback. `interpretation_postprocess.py` — dedup, overlap flagging, ID validation. `readiness.py` — interpretation-ready tag lifecycle. `theme_loading_for_interpretation.py` — approved theme graph queries. `templates/interpretation_synthesis_*.j2` — Jinja2 prompt templates.

## Dependencies

Depends on ontology layer for DAG traversal and `is_contiguous_subtree()` validation. Relies on theme inference output (only approved themes feed in). Uses the same shared infrastructure as all inference services: batch_processor, groq_client, status_updates, tracking, retry.

## References

Implements ADR-010 (LLM Inference). Consumes output from theme inference (`@docs/feature/theme-inference.md`). See `@ADR.md` and `@docs/feature/inference-layer.md` for shared infrastructure details.
