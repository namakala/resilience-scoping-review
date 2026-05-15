---
title: "Orchestration Layer"
description: "Coordinates workflow stages, state management, and layer integration"
updated_at: "2026-05-15"
---

# Python Orchestration Layer

Entry point and orchestration for the thematic analysis pipeline. Coordinates all stages from loading artifacts to exporting results.

## Purpose

Glue system components together. Manage workflow progression, checkpoint state, and delegate to specialized layers. Provide CLI interface and configuration management.

## Core Responsibilities

- Parse command-line arguments and load configuration
- Initialize Hamilton DAG for dependency orchestration
- Load immutable artifacts (exemplars, keywords, tag ontology)
- Drive workflow state machine through 10 stages
- Persist and restore session state for resumability
- Coordinate HITL review stages and capture user mutations
- Invoke semantic retrieval, LLM inference, and persistence layers
- Export final results (JSON, CSV, Markdown)

## Workflow Stages

Ten sequential stages define the analysis lifecycle:

1. **Load** — Read exemplars and tag ontology from CSV
2. **Embed** — Generate embeddings for exemplars and keywords (immutable)
3. **Index** — Build BM25 lexical index and ontology graph with traversal caches
4. **Infer Codes** — Batch Groq inference to generate initial codes from exemplars
5. **Review Codes** — HITL validation; approve, edit, merge, reject, defer
6. **Infer Themes** — Batch Groq inference to aggregate codes into themes per tag
7. **Review Themes** — HITL validation for thematic consolidation
8. **Infer Interpretations** — Batch Groq synthesis across multiple tags and themes
9. **Review Interpretations** — HITL validation for cross-tag insights
10. **Export** — Write final hierarchical results to disk

Each stage advances only when dependencies are satisfied. Revisiting earlier stages triggers selective recomputation of downstream stages.

## State Management

Workflow state tracks: current stage, dirty flags per ontology branch (which tags need recomputation), user action history, and session metadata (timestamps, config version). State persists to DuckDB. On startup, state is restored allowing resume from last checkpoint.

Dirty-state propagation (ADR-007) ensures only affected branches recompute after user edits. For example, editing a code invalidates its theme and any interpretation containing that theme.

## DAG Orchestration

Hamilton DAG encodes dependencies between computational nodes. Inputs: exemplars, keywords, ontology. Outputs: codes, themes, interpretations. Each node is a pure function; Hamilton determines execution order and caching behavior. DAG does not manage persistence or validation — those are delegated.

DAG construction takes a configuration object and returns executable object. Stages pass dataframes between nodes lazily where possible.

## Error Handling

Graceful degradation for infrastructure failures. Groq timeouts retry with exponential backoff (max three attempts). Rate limit errors wait 60 seconds before retry. Corrupted caches rebuild from source. User interrupts save state before exit. Invalid configurations produce clear error messages and exit.

## Integration Points

Delegates to layers:

- Semantic operations (`@src/python/semantic/AGENTS.md`): embedding generation, BM25 indexing, hybrid retrieval
- Ontology operations (`@src/python/ontology/AGENTS.md`): tag graph construction, constraint validation, traversal caches
- LLM inference (`@src/python/inference/AGENTS.md`): batch Groq calls, prompt templating, JSON parsing
- HITL review (`@src/python/hitl/AGENTS.md`): interactive CLI prompts, user action capture
- Persistence (`@src/python/persistence/AGENTS.md`): artifact loading and state checkpointing
- Graph database (`@src/python/graph/AGENTS.md`): node and edge CRUD operations
- Pipeline definition (`@src/python/pipeline/AGENTS.md`): Hamilton node function definitions and DAG wiring

## Testing

Unit tests cover config parsing, state transitions, artifact loading, and DAG node construction. Integration tests cover end-to-end workflow with mocked LLM responses, state persistence across restarts, and HITL interaction flows.

## References

Implements ADR-007 (Incremental Ontology Evolution) and ADR-008 (Pipeline Orchestration). See `@ADR.md` for architectural rationale.
