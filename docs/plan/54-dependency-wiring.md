---
title: "54 — dependency-wiring"
description: "Wire inputs/outputs between nodes in Hamilton DAG"
updated_at: "2026-05-12"
phase: 9
---

# Feature 54: dependency-wiring


---

## Description

Wire inputs/outputs between nodes. Example: `embed_exemplars` depends on `load_artifacts.exemplars` and `sentence_transformer.model`; `retrieve_candidates` depends on `embed_exemplars.embeddings`, `build_bm25.index`, `build_ontology.graph`; `infer_codes` depends on `retrieve_candidates.ranked_exemplars` and `prompt_templates.code_prompt`. Hamilton auto-resolves.

---

## Acceptance Criteria

- `dag.execution_plan()` shows correct topological ordering
- No missing dependencies (all inputs available from upstream)
- Data flow verified: downstream node receives correct type/shape
- Visualization renders legible DAG (nodes, edges)
- Override mechanism works: `executor.execute(overrides={'node': value})`

---

## Dependencies

@docs/plan/53-node-function-definitions.md

---

## Implementation Notes

- Module: `src/python/pipeline/wiring.py`
- In `create_pipeline()`, after constructing DAG, call `dag.to_dot()` or `dag.visualize()`
- Verify: `assert dag.validate()`; check for cycles
- Override test: in unit test, pass `overrides={'mock_llm': MockLLM()}` to replace real Groq client
- Visual inspection: generate Mermaid or Graphviz PNG

---

**References:** ADR-008
