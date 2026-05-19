"""Bootstrap resampling for uncertainty quantification.

Wraps any metric function with bootstrap CI computation.
Provides percentile-method 95% confidence intervals.
"""

from __future__ import annotations

from typing import Any, Callable, TypeVar

import numpy as np

F = TypeVar("F", bound=Callable[..., Any])


def bootstrap_ci(
    metric_fn: Callable[..., Any],
    mc_rows: list[dict[str, str]],
    hc_rows: list[dict[str, str]],
    n_iterations: int = 1000,
    alpha: float = 0.05,
    seed: int = 42,
    **metric_kwargs: Any,
) -> dict[str, Any]:
    """Compute bootstrap confidence intervals for a metric function.

    The *metric_fn* must accept ``mc_rows`` and ``hc_rows`` as positional
    args and return a float.  Returns::

        {
            "point_estimate": float,
            "ci_lower": float,     # alpha/2 percentile
            "ci_upper": float,     # 1 - alpha/2 percentile
            "n_iterations": int,
            "bootstrap_samples": [float, ...],  # all resampled values
        }
    """
    rng = np.random.default_rng(seed)

    # Compute point estimate on full data
    point = float(metric_fn(mc_rows, hc_rows, **metric_kwargs))

    # Bootstrap
    n = len(mc_rows)
    boot_samples: list[float] = []
    for _ in range(n_iterations):
        indices = rng.integers(0, n, size=n)
        mc_sample = [mc_rows[i] for i in indices]
        hc_sample = [hc_rows[i] for i in indices]
        try:
            val = float(metric_fn(mc_sample, hc_sample, **metric_kwargs))
            boot_samples.append(val)
        except Exception:
            continue

    if not boot_samples:
        return {
            "point_estimate": point,
            "ci_lower": point,
            "ci_upper": point,
            "n_iterations": 0,
            "bootstrap_samples": [],
        }

    boot_samples.sort()
    lower_idx = max(0, int(n_iterations * alpha / 2))
    upper_idx = min(len(boot_samples) - 1, int(n_iterations * (1 - alpha / 2)))

    return {
        "point_estimate": point,
        "ci_lower": float(boot_samples[lower_idx]),
        "ci_upper": float(boot_samples[upper_idx]),
        "n_iterations": len(boot_samples),
        "bootstrap_samples": [float(v) for v in boot_samples],
    }


def bootstrap_ci_dict(
    metric_fn: Callable[..., dict[str, float]],
    mc_rows: list[dict[str, str]],
    hc_rows: list[dict[str, str]],
    n_iterations: int = 1000,
    alpha: float = 0.05,
    seed: int = 42,
    **metric_kwargs: Any,
) -> dict[str, dict[str, float]]:
    """Bootstrap CI for dict-valued metrics.

    For each key in the dict (including ``_macro_avg``), computes a
    bootstrap CI.  Returns ``{key: {point_estimate, ci_lower, ci_upper,
    n_iterations}}``.
    """
    rng = np.random.default_rng(seed)
    n = len(mc_rows)
    all_keys: set[str] = set()

    # Determine keys from point estimate
    point = metric_fn(mc_rows, hc_rows, **metric_kwargs)
    all_keys = set(point.keys())

    # Collect bootstrap samples per key
    boot_by_key: dict[str, list[float]] = {k: [] for k in all_keys}
    for _ in range(n_iterations):
        indices = rng.integers(0, n, size=n)
        mc_sample = [mc_rows[i] for i in indices]
        hc_sample = [hc_rows[i] for i in indices]
        try:
            vals = metric_fn(mc_sample, hc_sample, **metric_kwargs)
            for k in all_keys:
                boot_by_key[k].append(float(vals.get(k, 0.0)))
        except Exception:
            continue

    result: dict[str, dict[str, float]] = {}
    for k in all_keys:
        samples = boot_by_key[k]
        if not samples:
            result[k] = {
                "point_estimate": float(point.get(k, 0.0)),
                "ci_lower": float(point.get(k, 0.0)),
                "ci_upper": float(point.get(k, 0.0)),
                "n_iterations": 0,
            }
            continue
        samples.sort()
        lower_idx = max(0, int(len(samples) * alpha / 2))
        upper_idx = min(len(samples) - 1, int(len(samples) * (1 - alpha / 2)))
        result[k] = {
            "point_estimate": float(point.get(k, 0.0)),
            "ci_lower": float(samples[lower_idx]),
            "ci_upper": float(samples[upper_idx]),
            "n_iterations": len(samples),
        }
    return result
