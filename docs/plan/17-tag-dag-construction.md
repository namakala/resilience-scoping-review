---
title: "17 — tag-dag-construction"
description: "Load tags.parquet; build NetworkX DAG; compute depth; validate acyclic"
updated_at: "2026-05-13"
phase: 3
---

# Feature 17: tag-dag-construction


---

## Description

Load `tags.parquet`. Construct NetworkX `DiGraph` of tags with `parent-child` edges from `parent` column. Compute `depth` for each tag (root=0). Validate graph is acyclic; if cycle detected, abort with error. Tag nodes stored as graph nodes with attributes: `tag_str`, `description`, `depth`, `n_contents` (from ontology, mutable as counts update).

---

## Acceptance Criteria

- DAG size = number of rows in tags.parquet
- Every tag except roots has at least one parent; every parent exists in graph
- `depth` computed correctly via shortest path from root
- `topological_sort()` succeeds
- Validation function `validate_tag_dag()` raises `CycleError` with cycle path if invalid
- Cached in memory as `ontology_graph` singleton

---

## Dependencies

@docs/plan/06-artifact-loaders.md

---

## Implementation Notes

- Module: `src/python/ontology/dag.py`
- Read tags via `load_tags()`; expect columns: `tag`, `parent`, `description`, `n_contents`
- Edge direction: parent → child (DAG)
- `depth` via `nx.shortest_path_length` from root to node
- Topological sort: `list(nx.topological_sort(G))`
- Cache: module-level `_ONTOLOGY_GRAPH` singleton; rebuild on demand

---

**References:** ADR-003 (Hierarchical Ontology Representation)
