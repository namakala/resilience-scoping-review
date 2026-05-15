---
title: "Pipeline Module"
description: "Hamilton DAG construction, node functions, and dependency-based workflow orchestration"
updated_at: "2026-05-15"
---

# Pipeline Module

Defines the computational DAG using Hamilton. Orchestrates embedding, retrieval, inference, review, and export stages with incremental recomputation.

## Constructor

``create_pipeline(config)`` in ``constructor.py`` builds a Hamilton ``Driver`` via ``Builder().with_modules(nodes.*).with_config({'config': config}).build()``. The ``Config`` dataclass (``config.py``) snapshots all env settings at pipeline creation time for typed dependency injection.

## Node Package

``nodes/`` defines 15 stub functions (13 main + 2 supporting) that Hamilton auto-discovers as DAG nodes. Functions are plain Python — no decorators needed. Parameter names matching function names resolve as dependencies. ``config: Config`` is injected via Hamilton's config dict.

## DAG Structure

Three inference chains:
1. Exemplars → embeddings → BM25 + ontology → retrieval → code inference → code review
2. Codes → theme inference → theme review
3. Themes → interpretation synthesis → interpretation review → export

Each node is a pure function. Side effects (persistence, user I/O) occur outside DAG.

## Purpose

Transform raw artifacts into semantic outputs through dependency-driven stages. Only recompute branches affected by user mutations or data changes.

## Core Responsibilities

- Construct Hamilton DAG from configuration
- Define node functions for each transformation (embed, retrieve, infer)
- Encode dependencies between stages
- Support selective execution (dirty flag propagation)
- Avoid managing persistence or validation logic

## DAG Structure

Three inference chains operate independently. First: exemplars→keywords→embeddings merge with ontology→graph to feed hybrid_retrieval and code_inference. Second: codes→code_embeddings merge with ontology traversal to feed theme_inference. Third: themes→theme_embeddings merge with ontology subtree to feed interpretation_synthesis.

Each node is a pure function. Inputs are explicit parameters. Outputs are dataframes or objects. Side effects (persistence, user interaction) occur outside DAG.

## Incremental Recomputation (ADR-007)

Hamilton tracks data dependencies. When a code is edited:

1. dirty_flags set for that branch
2. DAG detects affected nodes (code embedding, downstream retrieval, theme inference)
3. Only dirty nodes re-execute; clean nodes retrieved from cache

This avoids full re-inference. Supports interactive, iterative research workflow.

## Separation of Concerns

Hamilton DAG handles computation only. It delegates to other layers:

- **Persistence**: `@src/python/persistence/AGENTS.md` loads and saves state
- **Validation**: `@src/python/ontology/AGENTS.md` enforces constraints
- **User interaction**: `@src/python/hitl/AGENTS.md` handles CLI review
- **Semantic operations**: `@src/python/semantic/AGENTS.md` provides retrieval
- **LLM inference**: `@src/python/inference/AGENTS.md` manages Groq calls

Hamilton integrates them into a single executable pipeline.

## Node Categories

Three node types:

1. **Config nodes**: Load configuration, initialize API clients
2. **Data nodes**: Load artifacts (exemplars, ontology), generate embeddings, build indices
3. **Transformation nodes**: Perform inference, apply retrieval, aggregate results

Each node declares inputs and outputs. Hamilton resolves the execution order automatically.

## Batch Processing

Hamilton batches are prepared per-tag per-stage. Batches respect Groq rate limits (15 exemplars per batch typical). Nodes handle batch submission, response aggregation, and error collection.

## Testing

DAG tests verify: correct dependency resolution, selective execution on dirty flags, cache hit accuracy, and graceful degradation on API errors.

## Dirty Flag Propagation

``dirty.py`` provides incremental recomputation for the Hamilton DAG (Feature 55, ADR-007)::

- ``propagate_dirty(con, tag)`` — marks *tag* and all its ontology ancestors dirty in ``session_state.dirty_flags``. When a code/theme is edited under ``Problem.Cause``, ancestors like ``Problem`` are also marked dirty so interpretation nodes spanning the broader subtree recompute.
- ``set_dirty(con, tag)`` — sets a single tag dirty without upward propagation.
- ``clear_dirty(con, tag)`` / ``clear_all_dirty(con)`` — clears dirty flags after recomputation.
- ``is_dirty(tag, dirty_flags)`` / ``any_tag_dirty(tags, dirty_flags)`` — pure functions used by inference nodes to check whether a batch needs processing.

Three inference nodes (``infer_codes``, ``infer_themes``, ``infer_interpretations``) accept ``dirty_flags`` as a Hamilton external input. Batches whose tag is NOT dirty are skipped — the LLM is not called, and cached results are returned from the persistence layer. When ``dirty_flags`` is ``None`` (not provided), all batches are processed (backward-compatible).

## Wiring Utilities

``wiring.py`` provides optional DAG validation tools that operate on a built ``Driver``:
- ``verify_dag_integrity(driver)`` — structured health report (node count, cycles, deps, topological order, orphans, terminals)
- ``validate_dataflow(driver, final\_vars, inputs, overrides)`` — execution plan validity check wrapping ``Driver.validate_execution()``
- ``execute_with_overrides(driver, final\_vars, overrides, inputs)`` — override injection for tests and controlled runs

``mermaid.py`` provides Mermaid visualization:
- ``render_dag_mermaid(driver, path, final_vars, overrides)`` — Mermaid flowchart with layer clustering, override highlighting, and subgraph filtering

The constructor does not depend on either module; consumers import them when validation or visualization is needed.

## References

Implements ADR-008 (Pipeline Orchestration) and ADR-007 (Incremental Ontology Evolution). See `@ADR.md` for architectural decisions.
