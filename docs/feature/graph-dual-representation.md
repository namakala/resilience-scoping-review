---
title: "Graph Dual Representation"
description: "In-memory NetworkX and persistent DuckDB architecture, lifecycle, and traversal caching"
updated_at: 2026-05-13
---

# Graph Dual Representation

The knowledge graph uses a dual-model approach: NetworkX for fast in-memory traversal, DuckDB for durable storage.

## Architecture

```mermaid
graph TB
    subgraph "Persistence Layer"
        DUCKDB[DuckDB File<br/>data/output/session.duckdb]
        NODES[(nodes table)]
        EDGES[(edges table)]
        TRAV_CACHE[(traversal_cache<br/>JSON arrays)]
        STATE[(session_state<br/>user_actions<br/>embedding_cache)]
    end

    subgraph "In-Memory Layer"
        NETWORKX[NetworkX DiGraph<br/>Singleton]
        subgraph "Node Attributes"
            ATTR1[type, name, definition, tag, status]
        end
        subgraph "Edge Attributes"
            ATTR2["type, metadata<br/>(deserialized JSON)"]
        end
    end

    DUCKDB -->|"builder.build_graph()"| NETWORKX
    NETWORKX -->|"singleton.get_graph()"| APP[Application Layers]

    APP -->|"sync_node()/sync_edge()"| NETWORKX
    NETWORKX -->|"persisted via<br/>create_node/create_edge"| DUCKDB

    NETWORKX --> ATTR1
    NETWORKX --> ATTR2

    style DUCKDB fill:#e1f5ff
    style NETWORKX fill:#ffe8cf
    style APP fill:#e1ffe1
```

## Graph Lifecycle

1. **Lazy initialization** — First `get_graph()` call triggers `builder.build_graph(con)` which queries all `nodes` and `edges` from DuckDB and constructs a NetworkX `DiGraph`
2. **Singleton caching** — Graph cached globally; subsequent calls return same object (no rebuild)
3. **Explicit rebuild** — `rebuild_graph()` clears cache and reconstructs from DuckDB (useful after bulk mutations)
4. **Incremental sync** — After individual mutations, `sync_node(id)` and `sync_edge(source, target, type)` fetch the latest row from DuckDB and upsert into the in-memory graph

> **Performance target:** <5 seconds to build a 10,000-node graph (verified by unit test). See `graph-usage-performance.md` for full benchmarks.

## Traversal Caching (ADR-012)

Repeated subtree traversals during interpretation synthesis are expensive. Commonly used traversal results are materialized:

```mermaid
erDiagram
    TRAVERSAL_CACHE {
        VARCHAR tag PK
        VARCHAR ancestors
        VARCHAR descendants
        VARCHAR subtree_exemplars
        VARCHAR subtree_codes
        VARCHAR subtree_themes
    }

    NODES ||--o{ TRAVERSAL_CACHE : "one row per tag"
    EDGES }o--|| NODES : "parent-child edges define"

    TRAVERSAL_CACHE }o--|| TAG_NODE : "covers"
```

**Cached fields** per tag:
- `ancestors`: all parent tags up to root (for inheritance)
- `descendants`: all child tags down to leaves (for scope)
- `subtree_exemplars`: aggregated exemplar IDs in the tag's entire subtree
- `subtree_codes`: aggregated code IDs in subtree
- `subtree_themes`: aggregated theme IDs in subtree

**Invalidation policy** — Cache invalidated incrementally when:
- New tag added/modified (parent-child edge changed)
- Code moved to different tag
- Theme composition changes
- Only affected tag branches are recomputed (not the entire cache)
