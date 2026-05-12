---
title: "Pipeline Module"
description: "Hamilton DAG construction, node functions, and dependency-based workflow orchestration"
updated_at: "2026-05-11"
---

# Pipeline Module

Defines the computational DAG using Hamilton. Orchestrates embedding, retrieval, and inference with incremental recomputation.

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

## References

Implements ADR-008 (Pipeline Orchestration) and ADR-007 (Incremental Ontology Evolution). See `@ADR.md` for architectural decisions.
