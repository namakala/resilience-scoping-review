---
title: "Project Agentic Documentation Index"
description: "Entry point for agentic documentation across all system layers and modules"
updated_at: "2026-05-11"
---

# Local-First Qualitative Thematic Analysis

Reproducible local-execution pipeline for qualitative research. Processes exemplars under hierarchical tags, extracts keywords, and iteratively infers codes, themes, interpretations with HITL validation.

## System Purpose

Ontology-guided thematic analysis. Supports keyword extraction, code generation, theme consolidation, interpretation synthesis, and human validation. Operates on laptop (8 GB RAM). Combines explicit ontology graphs, vector embeddings, BM25 lexical search, and constrained LLM reasoning.

## Artifacts

**Immutable** (source of truth, never regenerated without explicit invalidation):
- Exemplars (id, document, tag, content)
- Keywords (extracted once per exemplar)
- Tag ontology (hierarchical namespace)

**Mutable** (evolved via iteration and validation):
- Codes (from exemplars + keywords)
- Themes (from codes)
- Interpretations (from themes across branches)

## Architecture Layers

Five layers under `src/python/`:

- **Orchestration** (`@src/python/AGENTS.md`): CLI, config, state machine, workflow coordination
- **Semantic** (`@src/python/semantic/AGENTS.md`): Embeddings, BM25, hybrid retrieval
- **Ontology** (`@src/python/ontology/AGENTS.md`): Tag hierarchy, graph traversal, constraint validation
- **Inference** (`@src/python/inference/AGENTS.md`): Groq batching, prompting, JSON parsing
- **HITL** (`@src/python/hitl/AGENTS.md`): CLI review, user mutations, undo/redo

Two supporting modules:

- **Graph** (`@src/python/graph/AGENTS.md`): Low-level graph CRUD and persistence
- **Pipeline** (`@src/python/pipeline/AGENTS.md`): Hamilton DAG construction and orchestration

## Cross-Cutting Principles

**ADR-004 Graph-Centric:** Codes, themes, interpretations stored as nodes with explicit edges. Enables lineage tracking and dependency propagation.

**ADR-005 Embeddings:** Used for retrieval only. Immutable for exemplars/keywords. Mutable for codes/themes/interpretations. Recompute only on content change. Encode name + definition + evidence + ontology context.

**ADR-006 Retrieval:** Hybrid ranking: BM25 (lexical) + cosine similarity (semantic) + ontology proximity (structural). Order: scope → BM25 → embeddings → fusion.

**ADR-007 Incremental Evolution:** Dirty-state propagation. Only affected ontology branches recomputed after edits.

**ADR-008 Pipeline:** Hamilton DAG of pure functions. Tracks dependencies, executes selectively. Does not manage persistence or validation.

**ADR-009 Data Processing:** Polars lazy dataframes. Parquet columnar storage. DuckDB for graph queries and state.

**ADR-010 LLM Inference:** Groq batch JSON generation. Group by tag. Include ontology context and existing codes. LLM as constrained interpreter.

**ADR-011 HITL Validation:** CLI review with approve, edit, merge, reject, defer. Context includes exemplars, keywords, neighbors. Mutations update graph atomically.

## Data Formats

Exemplars CSV: `id,document,tag,content`. Tag ontology CSV: `tag,description,n_contents`. Stored as Parquet. Graph in DuckDB. Results exported as JSON.

## Constraints

One code → one theme. One theme → one interpretation. Themes aggregate codes within same tag only. Interpretations may span multiple tags. Tag ontology is a DAG.

See `@src/python/ontology/AGENTS.md` for validation rules.

## Quick Reference

Entry point: `python analyze.py --data data/raw/data.csv --tags data/raw/tags.csv`.
Stages: load → embed → index → infer_codes → review_codes → infer_themes → review_themes → infer_interpretations → review_interpretations → export.
Environment: mamba env from `environment.yml`, also local environment for secrets such as `GROQ_API_KEY`.

## Writing Agentic Documentation

Each AGENTS.md ≤100 lines. YAML frontmatter required (title, description ≤200 chars, updated_at). Use short, simple sentences. No code snippets. Describe algorithmic intent, not implementation. Cross-reference hierarchically only (higher → lower). Derive content from `@ADR.md`. Purpose over mechanics.

## Implementation Tracking

The project uses `PLANS.md` (root) as the master feature checklist. Every implementable feature is enumerated as `XX-name` across 11 phase files in `docs/plan/`. When implementing a feature:

1. Read the feature specification from the linked `docs/plan/XX-phase.md#feature-YY-name`.
2. Implement, test, and verify acceptance criteria.
3. Mark the corresponding line in `PLANS.md` as `[x]` and add a short note (commit hash or date).
4. Update `docs/plan/XX-phase.md` with any specification changes (revise description, criteria, dependencies).
5. Update the phase file's `updated_at` frontmatter.

If you add, remove, or restructure features, update the `PLANS.md` checklist and the affected phase file(s) accordingly. Keep `PLANS.md` as a clean, simple checklist — all details reside in the `docs/plan/` files.

## References

- Architecture Decision Record: `@ADR.md`
- Orchestration: `@src/python/AGENTS.md`
- Semantic retrieval: `@src/python/semantic/AGENTS.md`
- Ontology & graph: `@src/python/ontology/AGENTS.md`
- LLM inference: `@src/python/inference/AGENTS.md`
- HITL workflows: `@src/python/hitl/AGENTS.md`
- Persistence: `@src/python/persistence/AGENTS.md`
- Graph module: `@src/python/graph/AGENTS.md`
- Pipeline orchestration: `@src/python/pipeline/AGENTS.md`
