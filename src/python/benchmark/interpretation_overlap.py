"""Level 3 metrics: interpretation overlap.

HC lacks interpretation data, so Level 3 evaluates MC internal
consistency:
    3a: Interpretation-theme coherence — do interpretations accurately
        reflect their constituent themes?
    3b: Claim-evidence congruence — are claims in the interpretation
        narrative supported by its exemplars?

Both functions accept a precomputed embedding cache for performance.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

import numpy as np


def interpretation_theme_coherence(
    mc_rows: list[dict[str, str]],
    emb_cache: dict[str, np.ndarray] | None = None,
) -> dict[str, float]:
    """For each MC interpretation, compute average hybrid similarity
    between its constituent themes.

    Groups rows by interpretation name, then for each pairwise combo of
    themes, computes name cosine + exemplar Jaccard hybrid similarity.

    Returns ``{interpretation_name: coherence}`` plus ``"_macro_avg"``.
    """
    interp_themes: dict[str, dict[str, set[str]]] = defaultdict(
        lambda: defaultdict(set)
    )
    for row in mc_rows:
        interp_themes[row["interpretation"]][row["theme"]].add(row["id"])

    emb_cache = emb_cache or {}

    result: dict[str, float] = {}
    for interp, themes in interp_themes.items():
        theme_names = list(themes.keys())
        if len(theme_names) < 2:
            result[interp] = 1.0
            continue

        similarities: list[float] = []
        for i in range(len(theme_names)):
            for j in range(i + 1, len(theme_names)):
                ei = emb_cache.get(theme_names[i])
                ej = emb_cache.get(theme_names[j])
                nsim = float(ei @ ej) if ei is not None and ej is not None else 0.0

                ex_i = themes[theme_names[i]]
                ex_j = themes[theme_names[j]]
                union = ex_i | ex_j
                esim = len(ex_i & ex_j) / len(union) if union else 0.0

                similarities.append(0.5 * max(0.0, nsim) + 0.5 * esim)

        result[interp] = float(np.mean(similarities)) if similarities else 0.0

    if result:
        vals = [v for k, v in result.items() if k != "_macro_avg"]
        result["_macro_avg"] = float(np.mean(vals)) if vals else 0.0
    return result


def _extract_claims(narrative: str) -> list[str]:
    """Extract claim-like sentences (length > 20 chars) from a narrative."""
    import re

    sentences = re.split(r"[.?!]\s+", narrative)
    return [s.strip() for s in sentences if len(s.strip()) > 20]


def claim_evidence_congruence(
    mc_rows: list[dict[str, str]],
    mc_interpretations: list[dict[str, Any]],
    interpretation_narratives: dict[str, str] | None = None,
    emb_cache: dict[str, np.ndarray] | None = None,
) -> dict[str, dict[str, Any]]:
    """For each MC interpretation, measure how well claims are supported
    by constituent exemplar contents.

    Returns ``{interpretation_name: {claim_count, mean_congruence, ...}}``.
    """
    interp_exemplars: dict[str, list[str]] = defaultdict(list)
    interp_narratives: dict[str, str] = {}

    for row in mc_rows:
        interp_exemplars[row["interpretation"]].append(row["content"])

    if interpretation_narratives:
        interp_narratives.update(interpretation_narratives)
    else:
        for interp in mc_interpretations:
            interp_narratives[interp["name"]] = interp.get("definition", "")

    emb_cache = emb_cache or {}

    result: dict[str, dict[str, Any]] = {}
    for interp_name, exemplar_contents in interp_exemplars.items():
        narrative = interp_narratives.get(interp_name, "")
        if not narrative or not exemplar_contents:
            result[interp_name] = {
                "claim_count": 0,
                "mean_congruence": 0.0,
                "congruence_per_claim": [],
            }
            continue

        claims = _extract_claims(narrative)
        if not claims:
            result[interp_name] = {
                "claim_count": 0,
                "mean_congruence": 0.0,
                "congruence_per_claim": [],
            }
            continue

        # Evidence centroid from cached exemplar embeddings
        ex_vecs: list[np.ndarray] = []
        for content in exemplar_contents:
            e = emb_cache.get(content)
            if e is not None:
                ex_vecs.append(e)
        if not ex_vecs:
            result[interp_name] = {
                "claim_count": len(claims),
                "mean_congruence": 0.0,
                "congruence_per_claim": [],
            }
            continue

        evidence_centroid = np.mean(np.stack(ex_vecs, axis=0), axis=0)
        norm = np.linalg.norm(evidence_centroid)
        if norm > 0:
            evidence_centroid = evidence_centroid / norm

        congruences: list[float] = []
        for claim in claims:
            ce = emb_cache.get(claim)
            if ce is not None:
                congruences.append(float(max(0.0, ce @ evidence_centroid)))

        result[interp_name] = {
            "claim_count": len(claims),
            "mean_congruence": float(np.mean(congruences)) if congruences else 0.0,
            "congruence_per_claim": congruences,
        }

    if result:
        vals = [v["mean_congruence"] for k, v in result.items() if k != "_macro_avg"]
        macro = float(np.mean(vals)) if vals else 0.0
        result["_macro_avg"] = {
            "claim_count": sum(
                v["claim_count"] for k, v in result.items() if k != "_macro_avg"
            ),
            "mean_congruence": macro,
            "congruence_per_claim": [],
        }
    return result
