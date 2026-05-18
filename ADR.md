# Executive Summary

This project builds a local-first qualitative thematic analysis system using large language models (LLMs), semantic retrieval, and hierarchical ontology traversal.

The system processes qualitative exemplars stored in CSV format. Each exemplar belongs to an immutable hierarchical tag. The system extracts immutable keywords from each exemplar. These immutable artifacts become the source of truth for all downstream inference.

The system iteratively infers:

* codes from exemplars and keywords,
* themes from codes,
* interpretations from themes across ontology branches.

Codes, themes, and interpretations are mutable and evolve through iterative semantic refinement and human-in-the-loop (HITL) validation.

The architecture combines:

* explicit ontology graphs for hierarchy and traversal,
* vector embeddings for semantic similarity,
* BM25 for lexical retrieval,
* DAG orchestration for incremental recomputation,
* and constrained LLM reasoning for interpretive synthesis.

The system is optimized for:

* reproducibility,
* ontology evolution,
* incremental recomputation,
* local execution on low-resource hardware,
* and qualitative research defensibility.

---

# Architecture Decision Record (ADR)

## ADR-001 — System Purpose

### Status

Accepted

### Context

The project requires a reproducible qualitative thematic analysis system capable of:

* extracting keywords from qualitative exemplars,
* generating codes,
* consolidating themes,
* generating interpretations,
* evolving semantic ontology iteratively,
* and supporting human validation.

The system must operate locally on a laptop with 8 GB RAM.

### Decision

The system shall implement:

* ontology-guided thematic analysis,
* hierarchical tag traversal,
* constrained LLM inference,
* and incremental semantic graph evolution.

The system shall not rely solely on embeddings or unsupervised clustering.

### Consequences

Benefits:

* reproducible thematic analysis,
* stable semantic evolution,
* traceable ontology lineage,
* academically defensible outputs.

Trade-offs:

* higher architectural complexity,
* graph management overhead,
* ontology maintenance requirements.

---

## ADR-002 — Immutable Source of Truth

### Status

Accepted

### Context

The thematic analysis process evolves iteratively. However, raw evidence must remain stable and auditable.

### Decision

The following entities shall be immutable:

* tags,
* exemplars,
* keywords.

These entities become the canonical semantic evidence layer.

Two immutable input files shall exist:

* `data.csv`
* `tag-ontology.csv`

`data.csv` contains:

* id,
* document,
* tag,
* content.

`tag-ontology.csv` contains:

* tag hierarchy,
* tag description,
* metadata.

Keywords are extracted once and never regenerated unless manually invalidated.

### Consequences

Benefits:

* auditability,
* stable semantic grounding,
* reproducible downstream inference.

Trade-offs:

* keyword extraction errors require explicit invalidation workflows.

---

## ADR-003 — Hierarchical Ontology Representation

### Status

Accepted

### Context

Tags form a hierarchical semantic namespace:

* `Problem`
* `Problem.Cause`
* `Problem.Scope.Association`
* etc.

Some tags contain no exemplars but preserve semantic hierarchy.

Interpretations may span multiple branches and inherit descendant semantics.

### Decision

The system shall explicitly represent tags as a hierarchical ontology graph.

The ontology graph shall support:

* parent-child traversal,
* subtree expansion,
* inheritance-aware retrieval,
* interpretation aggregation across branches.

Hierarchy shall not be inferred from embeddings.

### Consequences

Benefits:

* explicit semantic structure,
* predictable traversal behavior,
* hierarchy-aware interpretation synthesis.

Trade-offs:

* graph maintenance complexity,
* additional traversal infrastructure.

---

## ADR-004 — Graph-Centric Architecture

### Status

Accepted

### Context

The system requires:

* semantic evolution,
* ontology lineage,
* subtree traversal,
* interpretation aggregation,
* and incremental invalidation.

### Decision

The system shall implement a heterogeneous knowledge graph containing:

* tags,
* codes,
* themes,
* interpretations,
* exemplars.

Supported edge types include:

* parent-child,
* contains,
* derived-from,
* supports,
* merged-into,
* evolved-from.

### Consequences

Benefits:

* ontology lineage tracking,
* flexible semantic traversal,
* efficient dependency propagation.

Trade-offs:

* graph persistence complexity,
* more advanced retrieval logic.

---

## ADR-005 — Embedding Strategy

### Status

Accepted

### Context

Embeddings support semantic similarity but cannot represent explicit hierarchy or ontology inheritance.

Codes, themes, and interpretations evolve iteratively.

### Decision

Embeddings shall be used only for semantic retrieval and similarity scoring.

Embeddings shall not define ontology structure.

Embedding policies:

* exemplar embeddings are immutable,
* keyword embeddings are immutable,
* code embeddings are mutable,
* theme embeddings are mutable,
* interpretation embeddings are mutable.

Mutable embeddings shall be recomputed only when semantic state changes.

Embedding representations shall include:

* entity name,
* definition,
* supporting evidence,
* ontology context.

### Consequences

Benefits:

* stable semantic retrieval,
* incremental recomputation,
* improved ontology matching.

Trade-offs:

* embedding lifecycle management complexity.

---

## ADR-006 — Retrieval Strategy

### Status

Accepted

### Context

Thematic analysis requires:

* semantic similarity,
* lexical consistency,
* ontology-aware retrieval.

Embeddings alone are insufficient.

### Decision

The system shall implement hybrid retrieval using:

* cosine similarity,
* BM25 lexical search,
* ontology proximity scoring.

Retrieval order:

1. graph scope restriction,
2. BM25 retrieval,
3. embedding retrieval,
4. hybrid reranking.

Final ranking shall combine:

* semantic similarity,
* lexical similarity,
* graph proximity.

### Consequences

Benefits:

* improved semantic consistency,
* better terminology preservation,
* hierarchy-aware retrieval.

Trade-offs:

* more complex ranking logic,
* additional indexing overhead.

---

## ADR-007 — Incremental Ontology Evolution

### Status

Accepted

### Context

Codes, themes, and interpretations evolve iteratively.

Full recomputation is computationally expensive.

### Decision

The system shall implement dependency-aware incremental recomputation.

Only affected ontology branches shall be invalidated and recomputed.

Dirty-state propagation shall be used for:

* code updates,
* theme revisions,
* interpretation revisions,
* ontology merges.

### Consequences

Benefits:

* reduced compute cost,
* scalable ontology evolution,
* efficient local execution.

Trade-offs:

* dependency tracking complexity.

---

## ADR-008 — Pipeline Orchestration

### Status

Accepted

### Context

The system contains dependency-based semantic transformations.

### Decision

The system shall use:

### Apache Hamilton

for DAG orchestration and incremental recomputation.

Hamilton shall orchestrate:

* embedding generation,
* retrieval,
* code inference,
* theme inference,
* interpretation synthesis,
* dependency invalidation.

Hamilton shall not manage:

* ontology persistence,
* graph traversal,
* domain validation rules.

### Consequences

Benefits:

* explicit dependencies,
* selective recomputation,
* improved observability.

Trade-offs:

* DAG maintenance overhead.

---

## ADR-009 — Data Processing Framework

### Status

Accepted

### Context

The system must operate within limited memory constraints.

### Decision

The system shall use:

### Polars

for dataframe processing.

Polars lazy execution shall be preferred using:

* `scan_csv`,
* `scan_parquet`.

Data shall be persisted primarily as:

* Parquet,
* DuckDB tables.

### Consequences

Benefits:

* low memory usage,
* efficient analytical processing,
* streaming-friendly execution.

Trade-offs:

* additional persistence coordination.

---

## ADR-010 — LLM Inference Strategy

### Status

Accepted

### Context

The system uses:

### Groq

with GPT OSS 120B under strict token and request limits.

### Decision

The system shall use batch inference.

Inference batches shall:

* group exemplars by tag,
* include ontology context,
* include existing codes and themes,
* use structured JSON outputs,
* be implemented via the ``Batch`` dataclass (tag, items, batch_index,
  total_batches, item_count, batch_id property),
* accept items implementing ``BatchableItem`` Protocol (``.tag``,
  ``.id``),
* split tags exceeding 15 items into multiple batches,
* preserve item order by ``.id`` within each batch.

The LLM shall act as:

* semantic adjudicator,
* constrained interpreter,
* ontology refinement assistant.

The LLM shall not independently define ontology structure.

### Consequences

Benefits:

* lower token cost,
* improved consistency,
* stable ontology evolution.

Trade-offs:

* prompt engineering complexity.

---

## ADR-011 — Human-in-the-Loop Validation

### Status

Accepted

### Context

Qualitative thematic analysis requires interpretive validation.

### Decision

The system shall implement CLI-based HITL review.

Review stages:

* code validation,
* theme validation,
* interpretation validation.

Each review item shall include:

* source exemplars,
* keywords,
* ontology context,
* rationale,
* semantic neighbors.

The CLI shall support:

* approve,
* edit,
* merge,
* reject,
* defer.

### Consequences

Benefits:

* lightweight workflow,
* reproducible review process,
* researcher control.

Trade-offs:

* slower iterative refinement compared to fully automated systems.

---

## ADR-012 — Graph Traversal Optimization

### Status

Accepted

### Context

Interpretations require recursive subtree traversal.

Repeated graph traversal is computationally expensive.

### Decision

The system shall maintain materialized traversal caches for:

* descendants,
* ancestors,
* subtree exemplars,
* subtree codes,
* subtree themes.

Traversal caches shall be incrementally invalidated on ontology changes.

### Consequences

Benefits:

* faster ontology traversal,
* efficient interpretation synthesis,
* reduced repeated graph computation.

Trade-offs:

* cache invalidation complexity.

---

## ADR-013 — Ontology Constraints

### Status

Accepted

### Context

Thematic relationships must remain semantically consistent.

### Decision

The ontology shall enforce:

* one exemplar belongs to one code,
* one code belongs to one theme,
* one theme contains multiple codes within the same tag,
* one theme belongs to one interpretation,
* one interpretation may span multiple tags.

Interpretations may aggregate descendant branches automatically through subtree traversal.

### Consequences

Benefits:

* stable semantic organization,
* predictable ontology evolution,
* simplified traversal logic.

Trade-offs:

* reduced flexibility for overlapping thematic structures.
