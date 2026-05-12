---
title: "11 — networkx-graph-construction"
description: "Build in-memory NetworkX DiGraph from DuckDB nodes and edges"
updated_at: "2026-05-12"
phase: 2
---

# Feature 11: networkx-graph-construction


---

## Description

On system startup, load all nodes and edges from DuckDB tables `nodes` and `edges`. Construct a NetworkX `DiGraph`. Each node gets attributes: `type` (code/theme/interpretation/tag), `name`, `definition`, `tag`, `status`. Each edge gets `type` and `metadata`.

---

## Acceptance Criteria

- Graph built in <5 seconds for 10,000 nodes
- Graph structure exactly matches persistent state (node count, edge count, attributes)
- Tag nodes (from ontology) marked as `type='tag'` and `status='immutable'`
- In-memory graph kept in sync with DuckDB via update functions (not automatic)
- Unit test: insert node via API → graph reflects new node

---

## Dependencies

@docs/plan/07-duckdb-schema-init.md
@docs/plan/08-embedding-cache-schema.md

---

## Implementation Notes

- Module: `src/python/graph/networkx_wrapper.py`
- Query: `SELECT * FROM nodes` → iterate rows → `G.add_node(node_id, **attrs)`
- Query: `SELECT * FROM edges` → `G.add_edge(source_id, target_id, **attrs)`
- Cache graph as global singleton; rebuild on demand
- Use `nx.readwrite.json_graph` for debugging serialization

---

**References:** ADR-004 (Graph-Centric)
