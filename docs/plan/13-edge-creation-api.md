---
title: "13 — edge-creation-api"
description: "create_edge() – insert labeled edges with metadata"
updated_at: "2026-05-12"
phase: 2
---

# Feature 13: edge-creation-api


---

## Description

Function `create_edge(source_id: int, target_id: int, edge_type: str, metadata_json: dict | None = None)`. Edge types limited to: `parent-child`, `contains`, `derived-from`, `composed-of`, `spans`, `neighbor`. Inserts into DuckDB `edges` and adds to NetworkX.

---

## Acceptance Criteria

- Edge inserted with composite primary key `(source_id, target_id, edge_type)`
- Duplicate edge raises `ValueError`
- Source and target nodes must exist, else `ForeignKeyError` raised
- Metadata stored as JSON; `None` stored as empty dict
- NetworkX edge added with same attributes
- Batch variant `create_edges(edge_list)` available for bulk operations

---

## Dependencies

@docs/plan/11-networkx-graph-construction.md

---

## Implementation Notes

- Module: `src/python/graph/crud.py`
- SQL: `INSERT INTO edges (source_id, target_id, edge_type, metadata_json) VALUES (?, ?, ?, ?)`
- Validate `edge_type` in allowed set; raise `ValueError` if invalid
- Batch: loop over list within single transaction
- Don't check for duplicate edges that are already marked `merged`; those are logical deletes

---

**References:** ADR-004
