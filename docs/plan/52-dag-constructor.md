---
title: "52 — dag-constructor"
description: "create_pipeline(config) → hamilton.DAG with all nodes"
updated_at: "2026-05-15"
phase: 9
---

# Feature 52: dag-constructor


---

## Description

`create_pipeline(config) → hamilton.DAG`. Nodes: `load_artifacts`, `embed_exemplars`, `embed_keywords`, `build_bm25`, `build_ontology`, `retrieve_candidates`, `infer_codes`, `review_codes`, `infer_themes`, `review_themes`, `infer_interpretations`, `review_interpretations`, `export`. DAG visualizable via `dag.visualize()`.

---

## Acceptance Criteria

- DAG constructed without circular dependencies
- Topological sort yields valid execution order
- Node count ≥13 main nodes + supporting nodes
- Config object passed to all nodes via dependency injection
- DAG serializable to JSON for debugging
- Unit test: `dag.validate()` passes

---

## Dependencies

@docs/plan/01-project-scaffolding.md  (hamilton installed)

---

## Implementation Notes

- Module: `src/python/pipeline/constructor.py`
- Import `import hamilton`; `from hamilton import registry, driver`
- Each node function decorated `@hub.operator` or `@hub.task`; config passed as `config` parameter
- Collect all node functions from modules: `from . import nodes`
- `def create_pipeline(config: Config) -> hamilton.DAG: return hamilton.GraphBuilder().with_nodes(*NODE_FUNCS).with_config(config).build()`
- Visualize: `dag.to_json()` or `dag.visualize(filename='dag.png')`

---

**References:** ADR-008 (Pipeline Orchestration)
