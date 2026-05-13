---
title: "Graph Retrieval & Evolution"
description: "Ontology-aware hybrid search and incremental evolution via dirty flag propagation"
updated_at: 2026-05-13
---

# Graph Retrieval & Evolution

The graph powers scope-aware retrieval and supports incremental evolution when entities are edited.

## Retrieval: Ontology-Aware Hybrid Search (ADR-006)

The graph powers scope-aware retrieval through a four-step pipeline:

```mermaid
flowchart TD
    QUERY["User Query<br/>'patient barriers'"]
    ONT[Ontology:<br/>Tag DAG]
    GRAPH[Knowledge Graph<br/>NetworkX]

    subgraph "Step 1: Scope"
        SCOPE[Scope Restriction<br/>Subtree: Problem.Cause + descendants]
    end

    subgraph "Step 2: Lexical"
        BM25[BM25 Search<br/>keyword match]
    end

    subgraph "Step 3: Semantic"
        EMB[Embedding Similarity<br/>cosine]
    end

    subgraph "Step 4: Fusion"
        FUSION[Weighted Rerank<br/>emb: 0.5, proximity: 0.3, BM25: 0.2]
    end

    subgraph "Step 5: Results"
        CANDIDATES[Codes + Themes<br/>ranked by relevance]
    end

    QUERY --> SCOPE
    ONT --> SCOPE
    SCOPE --> GRAPH
    GRAPH --> BM25
    GRAPH --> EMB
    BM25 --> FUSION
    EMB --> FUSION
    FUSION --> CANDIDATES

    style GRAPH fill:#e1f5ff
    style SCOPE fill:#ffe8cf
    style FUSION fill:#ffe8cf
```

**Scoring weights:**
- Embedding similarity: **0.5** (semantic relevance)
- Ontology proximity: **0.3** (tag inheritance depth)
- BM25 lexical: **0.2** (terminology match)

See `graph-data-model.md` for node/edge types used in retrieval.

## Incremental Evolution (ADR-007 + ADR-008)

When a code is edited, the system recomputes only the affected branch:

```mermaid
flowchart LR
    EDIT["User edits<br/>Code 'C123'"]

    subgraph "Invalidation"
        DIRTY[Mark dirty:<br/>code C123<br/>theme T456<br/>interpretation I789]
    end

    subgraph "DAG Execution"
        RECOMP[Recompute:<br/>code embedding<br/>code→code neighbors<br/>theme inference<br/>interpretation synthesis]
        SKIP[Skipunchanged:<br/>other themes<br/>other branches]
    end

    EDIT --> DIRTY
    DIRTY --> RECOMP
    RECOMP --> SKIP

    style EDIT fill:#ffe8cf
    style DIRTY fill:#ffe8cf
    style RECOMP fill:#ffe8cf
    style SKIP fill:#e1ffe1
```

**Dirty flag propagation:**
- Edit code → invalidate its theme → invalidate interpretations containing that theme
- Merge two codes → invalidate both source codes → invalidate merged target → propagated downstream
- Hamilton DAG skips execution of clean nodes (cache hit)

See `graph-dual-representation.md` for traversal caching details that accelerate this process.
