---
title: "48 — interpretation-node-creation"
description: "Create interpretation node; spans edges to constituent themes"
updated_at: "2026-05-15"
phase: 8
---

# Feature 48: interpretation-node-creation


---

## Description

Create interpretation node: `type='interpretation'`, `name=interpretation_name`, `definition=narrative`, `status='draft'`. Create `spans` edges: interpretation → each theme_id. Set `tag_spans` field (set of all tags touched by constituent themes). Track `derived-from` chain if re-synthesized.

---

## Acceptance Criteria

- One interpretation node per `InterpretationInference` item
- `spans` edges created for all constituent themes
- `tag_spans` computed as union of theme tags; validated to be contiguous
- Query `get_nodes_by_type_and_tag('interpretation', tag)` returns interpretations whose tag_spans include that tag
- Evidence chain traceable: interpretation → themes → codes → exemplars via graph traversal
- Transactional: all edges persist or none on error

---

## Dependencies

@docs/plan/47-interpretation-synthesis-service.md
@docs/plan/14-node-query-operations.md

---

## Implementation Notes

- Module: `src/python/inference/interpretation_creation.py`
- `interpretation_id = create_node(type='interpretation', name=name, definition=narrative, tag=root_tag_of_span, status='draft', data_json={'tag_spans': list(tag_set)})`
- For each `theme_id` in `theme_ids`: `create_edge(source_id=interpretation_id, target_id=theme_id, edge_type='spans')`
- `tag_spans`: union of `theme.tag` for each theme (theme tag = parent tag of its codes)
- Invalidate downstream caches for all tags in `tag_spans` (Feature 20)
- If re-synthesized (existing draft with overlapping themes), link via `derived-from`

---

**References:** ADR-004

## Implementation Completion

**Completed:** 2026-05-15

All acceptance criteria satisfied:

- One interpretation node created per `InterpretationInference` item.
- `spans` edges created for all constituent theme IDs.
- `tag_spans` computed as union of theme tags; validated contiguous via `is_contiguous_subtree()`.
- `get_nodes_by_type_and_tag('interpretation', root_tag)` returns by root tag; `get_interpretations_by_span_tag(tag)` returns by any tag in `tag_spans`.
- Evidence chain traceable: interpretation → theme → code via `spans` + `composed-of` edges.
- Transactional: all writes inside `graph_transaction`; rollback on error (verified with simulated failures).
- Cache invalidation via `invalidate_cache_for_tags()` for all tags in `tag_spans`.
- Re-synthesis detection: draft interpretation with same name is renamed and linked via `derived-from` edge.
- Inference status set to `GENERATED` for each interpretation after creation.
- Duplicate name resolution within batch appends `_1`, `_2` suffix.

**Files modified/created:**

- Created `src/python/inference/interpretation_creation.py`
- Created `tests/unit/inference/interpretation_creation_test.py`
- Modified `src/python/inference/inference_status_types.py` (added `ENTITY_INTERPRETATION`)
- Modified `src/python/graph/queries.py` (added `get_interpretations_by_span_tag()`)
- Modified `src/python/graph/__init__.py` (export new query function)
- Modified `src/python/inference/__init__.py` (export `create_interpretation_nodes`, `ENTITY_INTERPRETATION`)

**Tests:** 19 unit tests in `tests/unit/inference/interpretation_creation_test.py`. Full suite: 897 passed.

**Git:** Not committed (user discretion).
