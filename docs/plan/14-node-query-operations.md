---
title: "14 — node-query-operations"
description: "get_node, get_nodes_by_type_and_tag, get_node_by_name"
updated_at: "2026-05-12"
phase: 2
---

# Feature 14: node-query-operations


---

## Description

Query functions: `get_node(node_id)`, `get_nodes_by_type_and_tag(node_type, tag)`, `get_node_by_name(name, node_type=None)`. All query DuckDB first, then optionally sync to NetworkX (read-only). Return node dicts or Pydantic models.

---

## Acceptance Criteria

- `get_node` raises `KeyError` if not found
- `get_nodes_by_type_and_tag` returns list sorted by `node_id`
- `get_node_by_name` disambiguates by type if provided; raises `LookupError` if multiple matches without type filter
- All queries use DuckDB indexes (performance test: <10ms for 10,000 nodes)
- Results include all node attributes: id, type, name, definition, tag, status, data_json, timestamps

---

## Dependencies

@docs/plan/07-duckdb-schema-init.md

---

## Implementation Notes

- Module: `src/python/graph/queries.py`
- DuckDB indexes: `CREATE INDEX IF NOT EXISTS idx_nodes_type_tag ON nodes(type, tag)`
- prepared statements for repeated queries
- Results as `dict` or Pydantic `Node` model
- NetworkX considered source of truth for in-memory; queries hit DuckDB and optionally update graph cache

---

**References:** ADR-004
