---
title: "Benchmark Evaluation Module"
description: "Three-level benchmark comparing MC output against human-coded data: exemplar grounding, code/theme alignment, interpretation coherence"
updated_at: "2026-05-18"
---

# Benchmark Evaluation Module

Compares machine-coded (MC) thematic analysis output against human-coded (HC) benchmarks. Runs three levels of metrics with bootstrap uncertainty quantification and produces a structured report.

## Purpose

Evaluate trustworthiness and reproducibility of LLM-aided thematic analysis. Replace the obsolete `src/python/similarity.py` with a principled, multi-level comparison that leverages the full hierarchical structure of the pipeline output.

## CLI Usage

```
python analyze.py benchmark \
  --source data/raw/benchmark-hc1.csv \
  --source data/raw/benchmark-hc2.csv \
  --output data/output/benchmark-report.json \
  --bootstrap 1000
```

`--source` is repeatable. Each file must have columns: `id, document, tag, content, code, theme`. No limit on number of sources.

## Design

MC data loaded from DuckDB graph + Parquet exemplars via `orchestration.export` internals (`_gather_approved_nodes`, `_gather_exemplars`, `_build_csv`). HC data loaded from CSV directly. Both aligned to the intersection of exemplar IDs — only common IDs are evaluated.

Embeddings precomputed once for all unique texts (code names, theme names, exemplar contents, narrative claims) and cached in memory. Bootstrap resampling reuses the embedding cache — only exemplar sets are resampled.

## Modules

- `adapters.py` — Load MC from DuckDB, HC from CSV, align by exemplar ID
- `exemplar_agreement.py` — Level 1: Jaccard overlap, Krippendorff's alpha, ontology-weighted disagreement
- `semantic_alignment.py` — Level 2: max-pooled hybrid similarity, Hungarian optimal matching
- `interpretation_overlap.py` — Level 3: interpretation-theme coherence, claim-evidence congruence
- `bootstrap.py` — Percentile-method bootstrap CIs for scalar and dict-valued metrics
- `report.py` — JSON and Markdown formatters
- `benchmark.py` — Main entry point, CLI command, orchestration

## Metrics

**Level 1 — Exemplar Grounding:**
- 1a: Macro-average Jaccard of exemplar sets per code (0 = no overlap, 1 = identical)
- 1b: Krippendorff's alpha with nominal distance (Hayes & Krippendorff, 2007)
- 1c: Ontology-weighted disagreement — penalties scaled by tag distance

**Level 2 — Code/Theme Semantic Alignment:**
- 2a: Max-pooled hybrid similarity (name cosine 0.4 + exemplar Jaccard 0.6)
- 2b: Hungarian optimal bipartite matching (mean weight, fraction unmatched)

**Level 3 — Interpretation Coherence (MC internal):**
- 3a: Interpretation-theme coherence — average hybrid similarity between themes within each interpretation
- 3b: Claim-evidence congruence — cosine similarity between narrative claims and exemplar centroid

## Uncertainty Quantification

All scalar metrics wrap with percentile bootstrap (default 1000 iterations). Report includes point estimate + 95% CI for every metric. Dict-valued metrics bootstrap each key independently.

## References

Replaces `src/python/similarity.py`. See `@docs/benchmark-approach/index.md` for full methodology. See `@docs/benchmark-results/index.md` for current results.
