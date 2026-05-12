---
title: "43 — theme-node-creation"
description: "Convert ThemeInference to graph nodes and composed-of edges"
updated_at: "2026-05-12"
phase: 7
---

# Feature 43: theme-node-creation


---

## Description

Convert each `ThemeInference` item into a graph node and edges. Node: `type='theme'`, `name=theme_name`, `definition=narrative`, `tag=parent_tag` (inherited from constituent codes), `status='draft'`. Edges: `composed-of` from theme to each code_id. If theme re-generated, `derived-from` chain maintained.

---

## Acceptance Criteria

- One theme node per `ThemeInference` item
- `composed-of` edges correctly link theme → codes
- Query `get_nodes_by_type_and_tag('theme', tag)` returns all themes for that tag
- `derived-from` chain tracks theme evolution across re-inference
- All nodes and edges persisted transactionally
- Duplicate theme names within tag flagged (merge later in HITL)

---

## Dependencies

@docs/plan/42-theme-inference-service.md
@docs/plan/14-node-query-operations.md

---

## Implementation Notes

- Module: `src/python/inference/theme_creation.py`
- For each `ThemeInference` item:
  - `theme_id = create_node(type='theme', name=theme_name, definition=narrative, tag=parent_tag, status='draft', data_json={})`
  - For each `code_id` in `code_ids`: `create_edge(source_id=theme_id, target_id=code_id, edge_type='composed-of')`
  - Check for existing draft theme with same name; link via `derived-from` if regenerated
- Transaction via `graph_transaction()`
- Update `inference_status` for codes to `themed`

---

**References:** ADR-004
