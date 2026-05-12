---
title: "38 — code-node-creation"
description: "Convert CodeInference to graph nodes and contains edges"
updated_at: "2026-05-12"
phase: 6
---

# Feature 38: code-node-creation


---

## Description

Convert each `CodeInference` item into a graph node and edges. Node: `type='code'`, `name=code_name`, `definition=definition`, `tag=exemplar.tag` (inherited from source exemplar), `status='draft'`. Edge: `source=code_node_id`, `target=exemplar_id`, `type='contains'`. If code is re-generated (existing draft for same exemplar), link via `derived-from` to previous code node (versioning chain).

---

## Acceptance Criteria

- One code node per `CodeInference` item (even if duplicate names; dedup later via merge)
- `contains` edge creates many-to-many: one code can contain multiple exemplars; one exemplar can generate multiple codes (but HITL will choose one)
- `derived-from` chain tracks evolution across re-inference runs
- All nodes and edges persisted transactionally
- Query `get_nodes_by_type_and_tag('code', tag)` returns all codes for that tag
- Time to create 100 code nodes <1s

---

## Dependencies

@docs/plan/37-code-inference-service.md
@docs/plan/14-node-query-operations.md

---

## Implementation Notes

- Module: `src/python/inference/code_creation.py`
- For each `CodeInference` item:
  - `node_id = create_node(type='code', name=code_name, definition=definition, tag=exemplar.tag, status='draft', data_json={...})`
  - `create_edge(source_id=node_id, target_id=exemplar_id, edge_type='contains')`
  - Check for existing draft code for same exemplar: `query = get_nodes_by_type_and_tag('code', tag) filter by exemplar linkage via data_json or separate table`; if found, create `derived-from` edge: source=existing, target=new
- Transaction: use `graph_transaction()` context manager
- Update `inference_status` to `status='generated'` for that exemplar

---

**References:** ADR-004 (Graph-Centric)
