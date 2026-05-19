"""JSON and Markdown formatters for benchmark reports.

Produces a structured JSON report and a human-readable Markdown summary
with paired-comparison tables, per-code/hybrid detail, and ontology
disagreement heatmaps.
"""

from __future__ import annotations

from typing import Any

CSV_COLUMNS = [
    "coder_pair",
    "metric",
    "point_estimate",
    "ci_lower",
    "ci_upper",
    "n_bootstrap",
]


def _fmt(v: float, places: int = 3) -> str:
    """Format a float to fixed decimal places."""
    return f"{v:.{places}f}"


def _ci_str(ci: dict[str, float] | None, places: int = 3) -> str:
    """Format a CI dict as ``point [lower, upper]``."""
    if ci is None:
        return "-"
    return (
        f"{_fmt(ci['point_estimate'], places)} "
        f"[{_fmt(ci['ci_lower'], places)}, "
        f"{_fmt(ci['ci_upper'], places)}]"
    )


def build_markdown(report: dict[str, Any]) -> str:
    """Build a Markdown report from the full benchmark results dict."""
    lines: list[str] = []
    lines.append("# Benchmark Evaluation Report")
    lines.append("")
    lines.append(f"- **Date:** {report.get('date', 'unknown')}")
    lines.append(f"- **Sources:** {', '.join(report.get('sources', []))}")
    lines.append(f"- **Common exemplars:** {report.get('common_exemplar_count', 0)}")
    lines.append(
        f"- **Bootstrap iterations:** " f"{report.get('bootstrap_iterations', 1000)}"
    )
    lines.append("")

    # ── Level 1: Exemplar Agreement ──
    lines.append("## Level 1: Exemplar Grounding Agreement")
    lines.append("")
    level1 = report.get("level1", {})
    _write_pairwise_table(lines, "1a: Macro-average Jaccard", level1, "macro_jaccard")
    _write_pairwise_table(
        lines, "1b: Krippendorff's Alpha", level1, "krippendorff_alpha"
    )

    # Ontology-weighted disagreement table
    lines.append("### 1c: Ontology-Weighted Disagreement by Pair")
    lines.append("")
    ontd = level1.get("ontology_weighted_disagreement", {})
    if ontd:
        lines.append("| Pair | Tag | Weighted Disagreement |")
        lines.append("|---|---|---|")
        for pair_key in sorted(ontd.keys()):
            pair_val = ontd[pair_key]
            if isinstance(pair_val, dict):
                for tag in sorted(pair_val.keys()):
                    v = pair_val[tag]
                    lines.append(f"| {pair_key} | {tag} | {_ci_str(v)} |")
            else:
                lines.append(f"| {pair_key} | _all_ | {_fmt(float(pair_val))} |")
        lines.append("")
    lines.append("### 1a Per-Code Jaccard Detail (top codes by disagreement)")
    lines.append("")
    jac_detail = level1.get("jaccard_per_code", {})
    if jac_detail:
        lines.append("| Pair | Code | Jaccard |")
        lines.append("|---|---|---|")
        for pair_key in sorted(jac_detail.keys()):
            per_code = jac_detail[pair_key]
            if isinstance(per_code, dict):
                # Show codes sorted by Jaccard ascending (most disagreement first)
                sorted_codes = sorted(per_code.items(), key=lambda x: x[1])
                for code, jac in sorted_codes[:15]:
                    lines.append(f"| {pair_key} | {code} | {_fmt(float(jac))} |")
        lines.append("")

    # ── Level 2: Semantic Alignment ──
    lines.append("## Level 2: Code/Theme Semantic Alignment")
    lines.append("")
    level2 = report.get("level2", {})
    _write_pairwise_table(
        lines,
        "2a: Max-Pooled Hybrid Similarity (macro avg)",
        level2,
        "max_pooled_macro_avg",
    )

    hung = level2.get("hungarian", {})
    lines.append("### 2b: Hungarian Optimal Matching")
    lines.append("")
    if hung:
        lines.append("| Metric | MC-HC1 | MC-HC2 | HC1-HC2 |")
        lines.append("|---|---|---|---|")
        for metric_key, metric_label in [
            ("mean_weight", "Mean similarity"),
            ("fraction_unmatched", "Fraction unmatched (MC/HC1 side)"),
        ]:
            vals = hung.get(metric_key, {})
            lines.append(
                f"| {metric_label} | {_ci_str(vals.get('MC_HC1'))} "
                f"| {_ci_str(vals.get('MC_HC2'))} "
                f"| {_ci_str(vals.get('HC1_HC2'))} |"
            )
        lines.append("")

    # ── Level 3: Interpretation Overlap ──
    lines.append("## Level 3: Interpretation Coherence (MC Internal)")
    lines.append("")
    level3 = report.get("level3", {})
    interp_coh = level3.get("interpretation_theme_coherence", {})
    if interp_coh:
        macro = interp_coh.get("_macro_avg", {})
        if isinstance(macro, dict):
            lines.append(
                f"- **3a: Interpretation-theme coherence (macro avg):** "
                f"{_ci_str(macro)}"
            )
        else:
            lines.append(
                f"- **3a: Interpretation-theme coherence (macro avg):** "
                f"{_fmt(float(macro))}"
            )
        lines.append("")

        lines.append("| Interpretation | Coherence |")
        lines.append("|---|---|")
        for name, val in sorted(interp_coh.items()):
            if name == "_macro_avg":
                continue
            if isinstance(val, dict):
                lines.append(f"| {name} | {_ci_str(val)} |")
            else:
                lines.append(f"| {name} | {_fmt(float(val))} |")
        lines.append("")

    claim_ce = level3.get("claim_evidence_congruence", {})
    if claim_ce:
        macro = claim_ce.get("_macro_avg", {})
        if isinstance(macro, dict):
            lines.append(
                f"- **3b: Claim-evidence congruence (macro avg):** " f"{_ci_str(macro)}"
            )
        lines.append("")

    return "\n".join(lines)


def _write_pairwise_table(
    lines: list[str],
    title: str,
    level_data: dict,
    key: str,
) -> None:
    """Add a pairwise comparison table section."""
    vals = level_data.get(key, {})
    lines.append(f"### {title}")
    lines.append("")
    lines.append("| Pair | Value |")
    lines.append("|---|---|")
    for pair in ["MC_HC1", "MC_HC2", "HC1_HC2"]:
        v = vals.get(pair)
        if v is not None:
            if isinstance(v, dict):
                lines.append(f"| {pair} | {_ci_str(v)} |")
            else:
                lines.append(f"| {pair} | {_fmt(float(v))} |")
    lines.append("")


def build_json(report: dict[str, Any]) -> dict[str, Any]:
    """Return the report structure as a JSON-serialisable dict (already is)."""
    return report


def build_report_dict(
    *,
    date: str,
    sources: list[str],
    common_exemplar_count: int,
    bootstrap_iterations: int,
    level1: dict[str, Any],
    level2: dict[str, Any],
    level3: dict[str, Any],
) -> dict[str, Any]:
    """Assemble the full report dictionary."""
    return {
        "date": date,
        "sources": sources,
        "common_exemplar_count": common_exemplar_count,
        "bootstrap_iterations": bootstrap_iterations,
        "level1": level1,
        "level2": level2,
        "level3": level3,
    }
