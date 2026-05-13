---
title: "12 — node-insertion-api"
description: "create_node() – insert node into DuckDB and NetworkX atomically"
updated_at: "2026-05-13"
phase: 2
---

# Feature 12: node-insertion-api


---

## Description

Function `create_node(node_type: str, name: str, definition: str, tag: str, status: str, data_json: dict) -> node_id`. Inserts into DuckDB `nodes` table and adds to in-memory NetworkX graph. Status values: `draft`, `approved`, `merged`, `rejected`.

---

## Acceptance Criteria

- Returns auto-incremented integer `node_id`
- DuckDB row inserted with all fields; `created_at = now()`
- NetworkX node added with same ID and attributes
- `data_json` serialized as JSON string; deserialized on read
- Duplicate name+type combination rejected with `ValueError`
- Transaction: both DuckDB and NetworkX updated, or neither on error

---

## Dependencies

@docs/plan/11-networkx-graph-construction.md

---

## Implementation Notes

- Module: `src/python/graph/node_crud.py`
- SQL: `INSERT INTO nodes (type, name, definition, tag, status, data_json) VALUES (?, ?, ?, ?, ?, ?)`
- Duplicate check: `SELECT 1 FROM nodes WHERE type=? AND name=? LIMIT 1`
- `data_json = json.dumps(data_dict)`; store as TEXT
- Use `graph_transaction()` context manager (Feature 16)

---

**References:** ADR-004
