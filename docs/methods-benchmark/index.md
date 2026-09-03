---
title: "Benchmark Evaluation Approach"
description: "Methodology for evaluating LLM-aided thematic analysis trustworthiness using three-level comparison against human-coded benchmarks"
updated_at: "2026-05-18"
---

# Benchmark Evaluation Approach

## Overview

The benchmark evaluation measures agreement between machine-coded (MC) thematic analysis output and human-coded (HC) benchmarks at three hierarchical levels: exemplar-to-code allocation, code/theme semantic alignment, and interpretation coherence. The evaluation employs seven metrics across these levels, each with bootstrap uncertainty quantification.

This approach replaces the earlier similarity analysis described in `@docs/results/_draft.md` (`src/python/similarity.py`). The earlier approach computed flat cosine similarity between code strings in a row-aligned CSV — an approach that conflated code content with code assignment, ignored exemplar grounding, and reported point estimates without confidence intervals.

## Data Sources

### Machine-Coded (MC) Data

The MC output is sourced from the DuckDB session database (`data/output/session.duckdb`) and the Parquet artifact store (`data/processed/`). The pipeline's export infrastructure (`@src/python/orchestration/export.py`) queries the graph for all approved nodes (codes, themes, interpretations) with status = 'approved', enriches them with exemplar and keyword data from Parquet, and builds a per-exemplar flat table with the schema:

```
id, document, tag, content, keywords, code, theme, interpretation
```

Each row represents one exemplar with its full analysis chain. The MC dataset contains 695 exemplars (as of the current pipeline run).

### Human-Coded (HC) Data

Human-coded data is provided as CSV files with the schema:

```
id, document, tag, content, keywords, code, theme
```

Each file represents one human coder (HC1, HC2). The HC datasets contain 100 exemplars each, sampled from the same literature base as the MC data. HC data lacks an `interpretation` column, so Level 3 metrics evaluate MC internal consistency rather than cross-coder agreement.

### Exemplar Alignment

Only exemplar IDs present in both MC and all HC sources are evaluated. The alignment procedure:
1. Build a lookup dict `{exemplar_id: row}` for each source.
2. Compute the set intersection of exemplar IDs across all sources.
3. Sort the common IDs and produce parallel lists `(mc_aligned, hc_aligned)`.

For the current benchmark (HC1 + HC2), the alignment yields **86 common exemplars** out of 539 unique MC IDs and 99 unique HC IDs.

## Level 1: Exemplar Grounding Agreement

Level 1 evaluates whether coders assign the same evidence (exemplars) to the same conceptual units (codes). This is the most grounded and defensible form of agreement — it measures analytical convergence directly, independent of naming conventions.

### 1a: Macro-Average Jaccard

For each code *c*, define the Jaccard index between two coders A and B:

$$J_c(A, B) = \frac{|E_{A,c} \cap E_{B,c}|}{|E_{A,c} \cup E_{B,c}|}$$

where *E<sub>A,c</sub>* is the set of exemplar IDs that coder A assigned to code *c*. Codes with zero exemplars from both coders are excluded. The macro-average is the mean of *J<sub>c</sub>* across all codes.

Range [0, 1]. 0 means no exemplar overlap on any code. 1 means identical exemplar-to-code assignments.

### 1b: Krippendorff's Alpha (Nominal)

Krippendorff's alpha ([@hayes2007answering]) measures inter-rater reliability with chance correction. For two coders with nominal assignment values (code names), alpha is:

$$\alpha = 1 - \frac{D_o}{D_e}$$

where *D<sub>o</sub>* is observed disagreement (pairs of values that differ) and *D<sub>e</sub>* is expected disagreement under independence (marginal product of code frequencies). The implementation builds the coincidence matrix from the unit-by-coder matrix and applies the nominal distance metric (0 for equal values, 1 for unequal).

Conventional thresholds: α > 0.67 for acceptable reliability, α > 0.80 for strong reliability.

### 1c: Ontology-Weighted Disagreement

When coders assign different code names to the same exemplar, the penalty is scaled by ontology distance between the codes' parent tags. Two codes in the same tag branch (e.g., both under `Resilience.Mechanism`) receive a lower penalty than codes in distant branches (e.g., `Resilience.Mechanism` vs `Problem.Impact.Mechanism`).

Ontology distance is computed as the shortest path length in the tag DAG, normalised by total tag count. The tag DAG is loaded from `tags.parquet` with parent-child relationships. Identity pairs have distance 0; disconnected pairs default to 1.0.

The mean ontology-weighted disagreement is reported per tag branch, identifying where coder divergence is concentrated.

## Level 2: Code/Theme Semantic Alignment

Level 2 evaluates whether coders produce semantically similar codes even when using different names. This captures a form of "conceptual convergence" — coders may label similar ideas differently but still agree on what the evidence means.

### 2a: Max-Pooled Hybrid Similarity

For each code *c<sub>A</sub>* in coder A, the best match in coder B is found by:

$$S(c_A, B) = \max_{c_B \in B} \left[ 0.4 \cdot \cos(e_{c_A}, e_{c_B}) + 0.6 \cdot J(c_A, c_B) \right]$$

where cos(*e<sub>cA</sub>, e<sub>cB</sub>*) is the cosine similarity between code name embeddings (all-MiniLM-L6-v2, 384-dim), and *J(c<sub>A</sub>, c<sub>B</sub>)* is the Jaccard similarity of exemplar sets. The macro-average is the mean across all codes in A.

Embeddings are precomputed once and cached. The 0.4/0.6 weighting prioritises exemplar overlap over name similarity, reflecting the principle that evidence grounding is more important than naming convention.

### 2b: Hungarian Optimal Matching

Hungarian algorithm ([@kuhn1955hungarian]) computes the maximum-weight bipartite matching between two coders' code sets, where edge weights are the hybrid similarity from 2a. Reports:

- **Mean weight**: average similarity of matched pairs
- **Fraction unmatched**: proportion of codes in set A with no match
- **Matched pairs**: the optimal alignment, showing which code maps to which

This metric reveals whether the two coders' coding schemes partition the evidence space in similar ways, independent of the number of codes produced.

## Level 3: Interpretation Coherence (MC Internal)

HC data lacks interpretation narratives, so Level 3 evaluates internal consistency of the MC interpretations rather than cross-coder agreement.

### 3a: Interpretation-Theme Coherence

For each MC interpretation, the average pairwise similarity between its constituent themes is computed. Each pair is scored as:

$$0.5 \cdot \cos(e_{t_i}, e_{t_j}) + 0.5 \cdot J_{ex}(t_i, t_j)$$

where cos is theme name embedding cosine and *J<sub>ex</sub>* is the Jaccard overlap between the themes' exemplar sets. The macro-average is reported across all interpretations.

Interpretations containing only one theme trivially score 1.0 (perfect coherence).

### 3b: Claim-Evidence Congruence

For each interpretation, the narrative is decomposed into claims (sentences exceeding 20 characters). Each claim is embedded and compared to the centroid embedding of all exemplars assigned to that interpretation:

$$\text{congruence} = \frac{1}{|C|} \sum_{c \in C} \max(0, \cos(e_c, \bar{e}_{ex}))$$

where *C* is the set of claims, *e<sub>c</sub>* is the claim embedding, and *ē<sub>ex</sub>* is the L2-normalised mean of exemplar content embeddings.

High congruence (>0.6) indicates the interpretation narrative is grounded in the evidence it claims to synthesise.

## Uncertainty Quantification

All scalar metrics are accompanied by 95% confidence intervals computed via percentile bootstrap ([@efron1994introduction]):

1. Resample the 86 aligned exemplars with replacement (1000 iterations).
2. Recompute the metric on each resample.
3. Sort the bootstrap distribution.
4. Report the 2.5th and 97.5th percentiles as the CI.

Dict-valued metrics (ontology-weighted disagreement, per-code Jaccard) bootstrap each key independently. The use of fixed precomputed embeddings ensures bootstrap iterations only re-sample exemplar sets, not recompute embeddings, making the procedure efficient.

## Comparison with the Earlier Approach

| Aspect | Earlier (similarity.py) | Current (benchmark module) |
|---|---|---|
| Unit of comparison | Row-aligned code strings | Unordered exemplar sets |
| Hierarchical levels | One (flat) | Three (code, theme, interpretation) |
| Exemplar grounding | None | Primary metric (Level 1) |
| Chance correction | None | Krippendorff's alpha |
| Uncertainty | None | Bootstrap 95% CI |
| Semantic similarity | Raw cosine on code text | Hybrid (embedding + exemplar overlap) |
| Code set alignment | Forced row-by-row | Hungarian optimal matching |
| MC data source | Hardcoded obsolete CSV | DuckDB + Parquet (live pipeline output) |

## Limitations

1. **Small benchmark sample**: 86 common exemplars is a modest sample size. Bootstrap CIs partially address this.
2. **Restricted tag coverage**: Human coders only coded exemplars under `Problem.Impact.Mechanism`, `Resilience.Mechanism`, and related subtags — approximately 15% of the MC ontology.
3. **No HC interpretations**: Level 3 evaluates MC internal consistency only. Pairwise interpretation comparison requires future HC interpretation production.
4. **Simple claim extraction**: Claim extraction uses sentence splitting rather than full NLP (spaCy triple extraction), which may miss implicit claims.
5. **Common ontology required**: Coders used the same tag ontology. Results may not generalise to open-coding scenarios where coders define their own categories.

## References

- [@hayes2007answering] Hayes, A. F., & Krippendorff, K. (2007). Answering the call for a standard reliability measure for coding data. *Communication Methods and Measures, 1*(1), 77–89.
- [@kuhn1955hungarian] Kuhn, H. W. (1955). The Hungarian method for the assignment problem. *Naval Research Logistics Quarterly, 2*(1-2), 83–97.
- [@efron1994introduction] Efron, B., & Tibshirani, R. J. (1994). *An Introduction to the Bootstrap*. Chapman and Hall.
- [@wang2020minilm] Wang, W., et al. (2020). MiniLM: Deep self-attention distillation for task-agnostic compression of pre-trained transformers. *NeurIPS*.
