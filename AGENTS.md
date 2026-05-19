---
title: "Project Agentic Documentation Index"
description: "Entry point for agentic documentation across all system layers and modules"
updated_at: "2026-05-18"
---

# Local-First Qualitative Thematic Analysis

Reproducible local-execution pipeline for qualitative research. Processes exemplars under hierarchical tags, extracts keywords, iteratively infers codes, themes, interpretations with HITL validation.

## System Purpose

Ontology-guided thematic analysis. Extracts keywords, generates codes, consolidates themes, synthesizes interpretations. Human validation at each stage. Operates on laptop (8 GB RAM). Uses explicit ontology graphs, vector embeddings, BM25 lexical search, and constrained LLM reasoning.

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

Supporting modules:
- **Graph** (`@src/python/graph/AGENTS.md`): Low-level CRUD
- **Pipeline** (`@src/python/pipeline/AGENTS.md`): Hamilton DAG orchestration

## Cross-Cutting Principles

**ADR-004 Graph-Centric:** Codes, themes, interpretations stored as graph nodes with explicit edges. Enables lineage tracking and dependency propagation.
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

One exemplar → one code. One code → one theme. One theme → one interpretation. Themes aggregate codes within same tag only. Interpretations may span multiple tags. Tag ontology is a DAG. All constraints are enforced at write time — violations produce logged warnings and skip the offending entity.

See `@src/python/ontology/AGENTS.md` for validation rules.

## Quick Reference

Entry point: `python analyze.py [global-opts] <command> [sub-opts]`.
Commands: `ingest` (load CSV data), `run [--all|--type]` (pipeline stages with HITL), `review` (HITL TUI).
No subcommand defaults to review (prompts to run if no artifacts exist).
Global options: `--data PATH`, `--tags PATH`, `--env FILE`, `--resume`.
Config: `.env` + optional `--env FILE` override. Precedence: CLI > --env > .env > defaults.
Stages: load → embed → index → infer_codes → review_codes → infer_themes → review_themes → infer_interpretations → review_interpretations → export.
Environment: mamba env from `environment.yml`, also local environment for secrets such as `GROQ_API_KEY`.

## Writing Agentic Documentation

Each AGENTS.md ≤100 lines. YAML frontmatter required (title, description ≤200 chars, updated_at). Short sentences. No code snippets. Describe algorithmic intent, not implementation. Cross-reference higher → lower.

## Implementation Tracking

Feature implementation: read plan → implement → test → mark `@PLANS.md` as `[x]` → update `updated_at`. Add/remove features by editing `@PLANS.md` and affected phase files.

## Standards Compliance

All code must follow `@STANDARDS.md`. Read it before implementing any feature.

When creating multiple files within a directory, always create or update the `AGENTS.md` in that directory.

## Environment Variables

All env vars documented in `.env.example` and configured via typed accessors in `src/python/config/`. See `@src/python/config/AGENTS.md` for the full settings catalog and conventions. Both files must stay in sync.

## References

- Architecture Decision Record: `@ADR.md`
- Coding Standards: `@STANDARDS.md`
- Orchestration: `@src/python/AGENTS.md`
- Semantic retrieval: `@src/python/semantic/AGENTS.md`
- Ontology & graph: `@src/python/ontology/AGENTS.md`
- LLM inference: `@src/python/inference/AGENTS.md`
- HITL workflows: `@src/python/hitl/AGENTS.md`
- Persistence: `@src/python/persistence/AGENTS.md`
- Graph module: `@src/python/graph/AGENTS.md`
- Pipeline orchestration: `@src/python/pipeline/AGENTS.md`
