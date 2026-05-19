"""Benchmark evaluation: compare MC output against human-coded benchmarks.

Provides metrics at three levels:
- Level 1: exemplar grounding (Jaccard, Krippendorff's alpha, ontology-weighted)
- Level 2: code/theme semantic alignment (hybrid similarity, Hungarian matching)
- Level 3: interpretation overlap (interpretation-theme coherence, claim-evidence)

Usage:
    python analyze.py benchmark --source data/raw/benchmark-hc1.csv \\
        --source data/raw/benchmark-hc2.csv
"""

from .benchmark import benchmark_cmd, run_benchmark

__all__ = ["run_benchmark", "benchmark_cmd"]
