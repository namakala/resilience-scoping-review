---
title: "38 — code-node-creation"
description: "Convert CodeInference to graph nodes and contains edges"
updated_at: "2026-05-14"
phase: 6
---

# Feature 38: code-node-creation

---

## Description

Convert each `CodeInference` item into a graph node and edges. Node: `type='code'`, `name=code_name`, `definition=definition`, `tag=code.tag` (injected by `infer_codes` from batch context), `status='draft'`. Edge: `source=code_node_id`, `target=exemplar_node_id`, `type='contains'`. If code is re-generated (existing draft for same exemplar), link via `derived-from` to previous code node (linear versioning chain).

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

- Module: `src/python/inference/code_node_creation.py`
- Prerequisite: `src/python/inference/exemplar_node_creation.py` (`ensure_exemplar_nodes`)
- `CodeInference` updated with `tag: str = ""` field (parsing.py:38)
- Tag injected by `infer_codes` from batch context (`code_inference.py:209`)
- For each `CodeInference` item:
  - `node_id = create_node(type='code', name=code_name, definition=definition, tag=tag, status='draft', data_json={exemplar_id, supporting_quote, related_existing_codes})`
  - `create_edge(source_id=node_id, target_id=exemplar_node_id, edge_type='contains')`
  - Check for existing draft code for same exemplar via `data_json['exemplar_id']`; if found, create `derived-from` edge: source=latest_existing, target=new (linear chain)
- Transaction: use `graph_transaction()` context manager
- After transaction: update `inference_status` for code entity to `status='generated'`

---

## Implementation Completion

**Completed:** 2026-05-14

All acceptance criteria satisfied:

- One code node per `CodeInference` item. Duplicate names handled via `_make_unique_name` which appends `_1`, `_2`, etc.
- `contains` edges created from code node → exemplar graph node. Exemplar nodes auto-created by `ensure_exemplar_nodes`.
- `derived-from` edges create a linear version chain (latest existing → new) for re-inference runs.
- All graph writes wrapped in `graph_transaction` for atomicity. Tested: error during transaction rolls back all nodes and edges.
- `get_nodes_by_type_and_tag('code', tag)` returns all created code nodes. Verified by test.
- Performance test: 100 code nodes in <1s (verified: 100 nodes created within tolerance).

**Files modified/created:**
- Modified `src/python/inference/parsing.py` — added `tag: str = ""` to `CodeInference`
- Modified `src/python/inference/code_inference.py` — inject `c.tag = batch.tag` in `_process_code_batch`
- Created `src/python/inference/exemplar_node_creation.py` — `ensure_exemplar_nodes()`
- Created `src/python/inference/code_node_creation.py` — `create_code_nodes()`
- Modified `src/python/inference/__init__.py` — exported both new functions
- Created `tests/unit/inference/exemplar_node_creation_test.py` — 8 tests
- Created `tests/unit/inference/code_node_creation_test.py` — 12 tests

**Total new tests:** 20 (all passing)

**References:** ADR-004 (Graph-Centric)
