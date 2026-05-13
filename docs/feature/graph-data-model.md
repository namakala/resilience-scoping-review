---
title: "Graph Data Model"
description: "Node and edge schemas, type catalogs, and core invariants for the knowledge graph"
updated_at: 2026-05-13
---

# Graph Data Model

## Overview

```mermaid
graph TD
    subgraph "Immutable Layer"
        TAG[Tag Node<br/>type: tag<br/>status: immutable]
        EX["Exemplar<br/>(Parquet artifact)<br/>not a graph node"]
        KW["Keywords<br/>(Parquet artifact)<br/>extracted once"]
    end

    subgraph "Mutable Layer"
        C[Code Node<br/>type: code<br/>status: draft/approved/merged]
        T[Theme Node<br/>type: theme<br/>status: draft/approved]
        I[Interpretation Node<br/>type: interpretation<br/>status: draft/approved]
    end

    subgraph "Edge Relationships"
        PC[parent-child<br/>Tag → Tag]
        CO[contains<br/>Code → Exemplar]
        DF["derived-from<br/>old → new<br/>(evolution chain)"]
        COF[composed-of<br/>Theme → Code]
        SP[spans<br/>Interpretation → Theme]
        NB["neighbor<br/>Code ↔ Code<br/>(similarity)"]
    end

    %% Primary semantic edges (solid)
    TAG1[ ] -->|PC| TAG2[ ]
    C -->|CO| EX
    T -->|COF| C
    I -->|SP| T

    %% Evolutionary chain edges (dotted)
    COld[ ] -.->|DF| CNew[ ]
    TOld[ ] -.->|DF| TNew[ ]
    IOld[ ] -.->|DF| INew[ ]
    C -.->|DF| C
    T -.->|DF| T
    I -.->|DF| I

    %% Similarity edges (dotted, undirected stored as two directed)
    C -.->|NB| C

    style TAG1 fill:#e1f5ff
    style TAG2 fill:#e1f5ff
    style EX fill:#f5e1e1
    style KW fill:#f5e1e1
    style C fill:#e1ffe1
    style T fill:#fff5e1
    style I fill:#f0e1ff
    style PC fill:#cfe8cf
    style CO fill:#cfcfe8
    style DF fill:#ffe8cf
    style COF fill:#e8cfcf
    style SP fill:#cfe8e8
    style NB fill:#f0cfcf
```

**Key design decision:** Exemplars are **not graph nodes**—they remain in Parquet files. Codes link to exemplars via `contains` edges, keeping the graph lean while preserving full traceability.

## Node Type Catalog

| Type | Mutability | Purpose |
|------|-----------|---------|
| `tag` | **Immutable** | Ontology namespace (e.g., `Problem`, `Problem.Cause`) |
| `code` | **Mutable** | Pattern derived from exemplars; status: draft → approved → merged/rejected |
| `theme` | **Mutable** | Aggregates codes within same tag; status: draft → approved → deprecated |
| `interpretation` | **Mutable** | Cross-tag synthesis; status: draft → approved → rejected |

Nodes stored in `nodes` table (DuckDB) and mirrored in NetworkX `DiGraph`. See `src/python/persistence/duckdb_schema.py` for full DDL.

## Edge Type Catalog

| Edge Type | Source → Target | Direction | Purpose |
|-----------|----------------|-----------|---------|
| `parent-child` | tag → tag | Directed | Ontology hierarchy; forms a DAG |
| `contains` | code → exemplar | Directed | Evidence linkage; code supported by exemplar |
| `derived-from` | code→code, theme→theme, interpretation→interpretation | Directed | Evolution chain; tracks revisions |
| `composed-of` | theme → code | Directed | Aggregation; theme aggregates codes (same-tag constraint) |
| `spans` | interpretation → theme | Directed | Semantic coverage; interpretation spans multiple tags |
| `neighbor` | code ↔ code | Undirected (stored as two directed edges) | Context for HITL review; similar codes |

Edges stored in `edges` table with composite PK `(source_id, target_id, edge_type)` and optional JSON `metadata_json`.

## Key Principles

- **One code → One theme:** Each `code` node has exactly one `composed-of` outgoing edge to a `theme` node
- **One theme → One interpretation:** Each `theme` node has exactly one `spans` outgoing edge to an `interpretation` node
- **Same-tag constraint:** All codes connected to a theme via `composed-of` must have the same `tag` value
- **Contiguous subtree:** `tag_spans` in `data_json` must form a connected sub-DAG
- **No cycles:** Tag DAG must remain acyclic; merge operations validated before edge creation
