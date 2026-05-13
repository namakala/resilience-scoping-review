---
title: "11 — networkx-graph-construction"
description: "Build in-memory NetworkX DiGraph from DuckDB nodes and edges"
updated_at: "2026-05-13"
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

**Module split into three focused files under `src/python/graph/`:**

- `singleton.py` — singleton lifecycle: `_graph` global, `get_graph(db_path)` lazy init, `rebuild_graph(db_path)` force refresh
- `builder.py` — pure construction: `build_graph(con)` queries nodes/edges, populates DiGraph, deserializes edge metadata JSON
- `sync.py` — explicit sync: `sync_node(node_id, db_path)` and `sync_edge(src, tgt, type, db_path)` for post-mutation updates

**Public API (re-exported via `__init__.py`):**
`get_graph`, `rebuild_graph`, `sync_node`, `sync_edge`, `build_graph` (testing/advanced)

**Node attributes:** `type` (code/theme/interpretation/tag), `name`, `definition`, `tag`, `status`

**Edge attributes:** `type` (parent-child/contains/derived-from/composed-of/spans/neighbor), `metadata` (dict or raw string)

**Performance:** Bulk `SELECT` + NetworkX `add_nodes_from`/`add_edges_from` → <5s for 10k nodes

**Testing:** Unit tests in `tests/unit/graph/`; integration tests in `tests/integration/graph/`

---

**References:** ADR-004 (Graph-Centric)
