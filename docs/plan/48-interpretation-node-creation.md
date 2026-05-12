---
title: "48 — interpretation-node-creation"
description: "Create interpretation node; spans edges to constituent themes"
updated_at: "2026-05-12"
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
