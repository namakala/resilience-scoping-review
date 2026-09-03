---
title: "Benchmark Evaluation Approach (Summary)"
description: "Three-paragraph summary of the methods used to compare machine-coded thematic analysis against human-coded benchmarks"
updated_at: "2026-05-18"
---

# Benchmark Evaluation Approach

The benchmark compared the machine-coded (MC) pipeline output against two human coders (HC1, HC2) on 86 exemplars common to MC and both HC datasets. Level 1 evaluation measured whether coders assigned the same exemplars to the same code names using macro-average Jaccard index and Krippendorff's alpha. Jaccard index measures the average exemplar set overlap per code, and Krippendorff's alpha measures chance-corrected inter-rater reliability with nominal distance. Ontology-weighted disagreement scaled the penalty when coders assigned different code names to the same exemplar, identifying where coder divergence concentrated.

Level 2 measured conceptual convergence when code names differed, using a weighted hybrid metric that combined name embedding cosine similarity (0.4) with exemplar set Jaccard index (0.6). An optimal bipartite matching via the Hungarian algorithm confirmed whether the two coding schemes partitioned the evidence in compatible ways, solving the difficulty that coders produce different numbers of codes at different levels of granularity. The algorithm built a similarity matrix between code sets, selected the optimal one-to-one matching, and reported mean similarity of matched pairs and fraction of unmatched codes.

Level 3 evaluated the internal consistency of MC interpretations, since HC data lacked interpretation narratives. Interpretation-theme coherence measured the average pairwise similarity between themes grouped under the same interpretation using a hybrid measure similar to Level 2. Claim-evidence congruence decomposed each interpretation narrative into claims and measured their semantic similarity to the centroid embedding of all supporting exemplar contents. All scalar metrics were reported with 95% confidence intervals from percentile bootstrap resampling with 1000 iterations.
