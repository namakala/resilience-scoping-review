---
title: "Graph Integration & Constraints"
description: "System integration, layer responsibilities, and constraint validation for the knowledge graph"
updated_at: 2026-05-13
---

# Graph Integration & Constraints

The knowledge graph integrates with all system layers and enforces structural invariants.

## System-Wide Integration

```mermaid
graph LR
    subgraph "Orchestration Layer"
        CLI[analyze.py CLI]
        DAG[Hamilton DAG<br/>pipeline.py]
    end

    subgraph "Supporting Layers"
        SEM[semantic/<br/>embeddings + BM25]
        ONT[ontology/<br/>tag DAG + constraints]
        INF[inference/<br/>Groq batching]
        HITL[hitl/<br/>CLI review]
    end

    subgraph "Persistence Layer"
        PERS[persistence/<br/>CSV → Parquet,<br/>DuckDB init,<br/>state mgmt]
        GRAPH[graph/<br/>NetworkX + DuckDB<br/>nodes/edges/traversal]
    end

    CLI --> DAG
    DAG --> SEM & ONT & INF & HITL
    SEM --> GRAPH
    ONT --> GRAPH
    INF --> GRAPH
    HITL --> GRAPH
    HITL --> PERS

    PERS --> GRAPH

    style GRAPH fill:#e1f5ff,stroke:#333,stroke-width:2px
    style CLI fill:#f0e1ff
    style DAG fill:#fff5e1
    style SEM fill:#e1ffe1
    style ONT fill:#e1ffe1
    style INF fill:#e1ffe1
    style HITL fill:#e1ffe1
    style PERS fill:#e1ffe1
```

## Layer Responsibilities

| Layer | Graph Usage |
|-------|-------------|
| **Persistence** | DuckDB schema (`nodes`, `edges`, `traversal_cache`); artifact loading |
| **Graph Module** | NetworkX construction, singleton, sync, (planned) CRUD APIs |
| **Ontology** | Tag DAG traversal, constraint validation (one-code-one-theme, etc.) |
| **Semantic** | Scope restriction (tag subtree queries), neighbor discovery |
| **Inference** | Prompt context (ontology path, existing codes/themes), write results |
| **HITL** | Present graph context (ancestors/descendants, evidence chains), persist mutations |
| **Pipeline** | Dirty flag propagation, selective DAG recomputation |

## Constraint Validation (ADR-013)

The graph enforces structural invariants through edge patterns:

| Constraint | Enforcement Mechanism |
|------------|----------------------|
| **One code → One theme** | Each `code` node has exactly one `composed-of` outgoing edge to a `theme` node |
| **One theme → One interpretation** | Each `theme` node has exactly one `spans` outgoing edge to an `interpretation` node |
| **Codes in same tag** | All codes connected to a theme via `composed-of` must have same `tag` value |
| **Interpretation spans contiguous subtree** | `tag_spans` set in `data_json` must form a connected sub-DAG (no disjoint branches) |
| **No cycles** | Tag DAG must remain acyclic; merge operations validated before edge creation |

These constraints are checked at three points:

- **On write** — CRUD API rejects violations before persistence
- **During review** — HITL actions validated before mutation is committed
- **On batch inference** — LLM outputs validated before graph insertion

See `graph-data-model.md` for the full node/edge type catalog.
