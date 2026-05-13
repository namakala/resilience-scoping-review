---
title: "Graph Usage & Performance"
description: "Direct API usage examples, schema migration strategy, file reference, and performance targets"
updated_at: 2026-05-13
---

# Graph Usage & Performance

## Access the Graph

```python
from graph import get_graph, rebuild_graph

G = get_graph()  # lazy singleton
print(f"Nodes: {G.number_of_nodes()}, Edges: {G.number_of_edges()}")
rebuild_graph()  # force rebuild after bulk mutations
```

## Query Nodes

```python
node_id = 123
node_attrs = G.nodes[node_id]
print(node_attrs['type'], node_attrs['name'], node_attrs['status'])
```

## Traverse Edges

```python
theme_id = 456
codes = list(G.successors(theme_id))  # edge type = 'composed-of'

tag_id = 789
parents = list(G.predecessors(tag_id))  # edge type = 'parent-child'
```

## Inspect Edge Metadata

```python
edge_data = G.get_edge_data(source_id, target_id)
edge_type = edge_data['type']
metadata = edge_data.get('metadata')  # deserialized JSON or None
```

## Evidence Chain Example

```mermaid
flowchart LR
    format("Exemplar 123<br/><em>'Patients reported...'</em>")

    format -.->|"contains"| C1["Code: 'Transportation Barrier'<br/>status: approved"]

    T1["Theme: 'Access Challenges'<br/>tag: Problem.Cause<br/>status: approved"] -->|"composed-of"| C1
    T1 -->|"composed-of"| C2["Code: 'Cost Barrier'"]
    T1 -->|"composed-of"| C3["Code: 'Geographic Barrier'"]

    T1 -->|"spans"| I1["Interpretation: 'Structural Barriers'<br/>tag_spans: [Problem.Cause, Problem.Scope]<br/>status: approved"]

    I1 -->|"spans"| T2["Theme: 'System Complexity'<br/>tag: Problem.Scope"]

    C4["Code v1: 'Expensive Transport'<br/>(old version)"] -.->|"derived-from"| C2
    C5["Code v1: 'Remote Location'<br/>(old version)"] -.->|"derived-from"| C3

    style format fill:#f5e1e1
    style C1 fill:#e1ffe1
    style C2 fill:#e1ffe1
    style C3 fill:#e1ffe1
    style C4 fill:#ffe8cf
    style C5 fill:#ffe8cf
    style T1 fill:#fff5e1
    style T2 fill:#fff5e1
    style I1 fill:#f0e1ff
```

**Chain traceability:** From interpretation down to raw exemplar quotes is always possible via graph traversal.

## Schema Migration Strategy

- **Version tracking** — `session_state` key `'schema_version'` (current = 1)
- **Forward-only migrations** — Applied sequentially via `duckdb_migrations.py`
- **Backward compatibility not guaranteed** — Recreate database if downgraded

## File Reference

**Graph module** (`src/python/graph/`): `builder.py` (DuckDB→NetworkX), `singleton.py` (lifecycle), `sync.py` (post-mutation sync), `__init__.py` (public API).

**Schema** (`src/python/persistence/duckdb_schema.py`): Table DDL for `nodes`, `edges`, `traversal_cache`, `session_state`, `user_actions`, `embedding_cache`.

**Documentation**: `src/python/graph/AGENTS.md` (module design), `ADR.md` (ADR-004, ADR-012, ADR-013), `PLANS.md` (features 11–16).

## Performance Targets

| Metric | Target | Current |
|--------|--------|---------|
| Build graph (10k nodes) | <5 seconds | ✅ (verified in test) |
| Traverse parent-child (single hop) | <10 ms | — |
| Subtree descendants (cached) | <5 ms | — (cache table exists, invalidation pending) |
| Sync single node | <20 ms | — (sync functions implemented, not yet integrated) |
