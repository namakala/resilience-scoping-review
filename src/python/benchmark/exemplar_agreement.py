"""Level 1 metrics: exemplar-to-code allocation agreement.

Three metrics:
    1a: Jaccard overlap per code, macro-averaged across coders.
    1b: Krippendorff's alpha with nominal distance (implemented inline).
    1c: Ontology-weighted disagreement: disagreement penalised less
        when codes share a parent tag.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

import numpy as np

# ── 1a: Jaccard overlap ────────────────────────────────────────────────


def jaccard_overlap(
    mc_code_map: dict[str, set[str]],
    hc_code_map: dict[str, set[str]],
) -> dict[str, float]:
    """Per-code Jaccard index between two coders' exemplar allocations.

    *mc_code_map* and *hc_code_map* map ``code_name → set[exemplar_id]``.
    Returns ``{code_name: jaccard}`` for every code appearing in either coder.
    Codes with zero exemplars in both sides are excluded.
    """
    all_codes = set(mc_code_map) | set(hc_code_map)
    result: dict[str, float] = {}
    for code in all_codes:
        a = mc_code_map.get(code, set())
        b = hc_code_map.get(code, set())
        union = a | b
        if not union:
            continue
        result[code] = len(a & b) / len(union)
    return result


def macro_jaccard(
    mc_code_map: dict[str, set[str]],
    hc_code_map: dict[str, set[str]],
) -> float:
    """Macro-average Jaccard across all codes."""
    scores = jaccard_overlap(mc_code_map, hc_code_map)
    if not scores:
        return 0.0
    return float(np.mean(list(scores.values())))


# ── 1b: Krippendorff's alpha (nominal) ────────────────────────────────


def _reliability_matrix(
    mc_assignments: dict[str, str],
    hc_assignments: dict[str, str],
) -> np.ndarray:
    """Build unit-by-coder nominal matrix.

    Rows = exemplars (sorted), columns = coders (MC, HC).
    Values are integer codes. Missing values encoded as NaN.
    Returns (n, 2) int matrix.
    """
    eids = sorted(mc_assignments.keys() & hc_assignments.keys())
    # Map unique code values to integers
    all_values = list(
        set(mc_assignments[eid] for eid in eids)
        | set(hc_assignments[eid] for eid in eids)
    )
    value_to_int = {v: i for i, v in enumerate(all_values)}

    matrix = np.zeros((len(eids), 2), dtype=np.float64)
    for i, eid in enumerate(eids):
        matrix[i, 0] = value_to_int[mc_assignments[eid]]
        matrix[i, 1] = value_to_int[hc_assignments[eid]]
    return matrix


def krippendorff_alpha(
    mc_assignments: dict[str, str],
    hc_assignments: dict[str, str],
) -> float:
    """Compute Krippendorff's alpha with nominal distance for two coders.

    Implementation follows Hayes & Krippendorff (2007)::

        α = 1 - Dₒ / Dₑ

    where Dₒ is observed disagreement and Dₑ is expected disagreement
    under independence.
    """
    eids = sorted(mc_assignments.keys() & hc_assignments.keys())
    if len(eids) < 2:
        return 0.0

    # Map values to integer codes
    all_values = list(
        set(mc_assignments[eid] for eid in eids)
        | set(hc_assignments[eid] for eid in eids)
    )
    v = {val: i for i, val in enumerate(all_values)}
    n_categories = len(v)
    n_coders = 2

    # Build coincidence matrix (n_categories × n_categories)
    coinc = np.zeros((n_categories, n_categories), dtype=np.float64)
    for eid in eids:
        mc_val = v[mc_assignments[eid]]
        hc_val = v[hc_assignments[eid]]
        coinc[mc_val, hc_val] += 1.0 / (n_coders - 1)
        # For two coders, the above gives 1.0 for each pair

    # Observed disagreement: sum coincidences where values differ
    observed = 0.0
    for cat_i in range(n_categories):
        for cat_j in range(n_categories):
            if cat_i != cat_j:
                observed += coinc[cat_i, cat_j]

    # Expected disagreement (independent marginal probabilities)
    column_sums = coinc.sum(axis=0)  # shape (n_categories,)
    total_pairs = column_sums.sum()
    if total_pairs == 0:
        return 0.0

    # For nominal metric, the distance is 0 when equal, 1 when different
    expected = 0.0
    for cat_i in range(n_categories):
        row_sum = coinc[cat_i, :].sum()
        for cat_j in range(n_categories):
            if cat_i != cat_j:
                expected += row_sum * column_sums[cat_j] / total_pairs

    if expected == 0:
        return 1.0
    return max(-1.0, 1.0 - observed / expected)


# ── 1c: Ontology-weighted disagreement ────────────────────────────────


def ontology_weighted_disagreement(
    mc_assignments: dict[str, dict[str, Any]],
    hc_assignments: dict[str, dict[str, Any]],
    ontology_dist: dict[str, dict[str, float]],
) -> dict[str, float]:
    """Compute ontology-weighted disagreement by tag branch.

    For each exemplar where MC and HC disagree on code assignment,
    the penalty is scaled by ontology distance between the codes'
    parent tags.  Two codes in the same tag branch get lower penalty.

    *ontology_dist* is a precomputed dict ``{tag_a: {tag_b: distance}}``
    where distance = 0 for identical tags and increases with ontology
    path length.

    Returns ``{tag_branch: mean_weighted_disagreement}`` broken down
    by the exemplar's own tag.
    """
    eids = sorted(mc_assignments.keys() & hc_assignments.keys())
    tag_disagreement: dict[str, list[float]] = defaultdict(list)

    for eid in eids:
        mc = mc_assignments[eid]
        hc = hc_assignments[eid]
        tag = mc.get("tag", "") or hc.get("tag", "")

        mc_code = mc.get("code", "")
        hc_code = hc.get("code", "")
        mc_tag = mc.get("tag", "")
        hc_tag = hc.get("tag", "")

        if mc_code == hc_code:
            tag_disagreement[tag].append(0.0)
        else:
            # Look up ontology distance between tags
            dist = ontology_dist.get(mc_tag, {}).get(hc_tag, 1.0)
            tag_disagreement[tag].append(dist)

    result: dict[str, float] = {}
    for tag, penalties in tag_disagreement.items():
        result[tag] = float(np.mean(penalties)) if penalties else 0.0
    return result


# ── Helper: build code → exemplar maps ────────────────────────────────


def build_code_map(rows: list[dict[str, str]]) -> dict[str, set[str]]:
    """Convert aligned dataframe rows to ``{code_name: {exemplar_id}}``."""
    code_map: dict[str, set[str]] = defaultdict(set)
    for row in rows:
        code_map[row["code"]].add(row["id"])
    return dict(code_map)


def build_assignment_map(
    rows: list[dict[str, str]],
) -> dict[str, str]:
    """Convert dataframe rows to ``{exemplar_id: code_name}``."""
    return {r["id"]: r["code"] for r in rows}
