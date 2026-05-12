---
title: "15 — basic-traversal"
description: "get_children, get_parents, get_path, get_successors, get_predecessors"
updated_at: "2026-05-12"
phase: 2
---

# Feature 15: basic-traversal


---

## Description

Graph traversal utilities: `get_children(node_id) → list[node_id]`, `get_parents(node_id) → list[node_id]`, `get_path(source_id, target_id) → list[node_id]` (shortest path), `get_successors(node_id)`, `get_predecessors(node_id)`. Use NetworkX for computation.

---

## Acceptance Criteria

- Returns ordered list (topological for children/parents; shortest path for get_path)
- Empty list if no neighbors
- `get_path` returns `None` if no path exists
- Cycle detection: graph is a DAG for tag hierarchy; if cycle detected, raise `CycleError`
- Traversals respect edge direction (DiGraph)
- Performance: path between depth-5 nodes <1ms

---

## Dependencies

@docs/plan/11-networkx-graph-construction.md

---

## Implementation Notes

- Module: `src/python/graph/traversal.py`
- Wrapper around `nx.bfs_successors`, `nx.bfs_predecessors`, `nx.shortest_path`
- `get_children` = immediate successors; `get_descendants` = all reachable (not in this feature, that's in ontology layer)
- `get_path` uses `nx.shortest_path(G, source, target)`
- Cache frequent queries: children of tag nodes, ancestors of deep tags

---

**References:** ADR-004
