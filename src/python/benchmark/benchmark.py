"""Benchmark orchestration: entry point for ``python analyze.py benchmark``.

Loads MC from DuckDB + Parquet (reusing export infrastructure), loads
HC from CSV, aligns by exemplar ID, runs all 3 levels of metrics with
bootstrap CIs, and writes the report.
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import click
import numpy as np
from config.config import Config
from persistence.duckdb_connection import get_connection
from utils.logging import get_logger

from .adapters import align_dataframes, load_hc_dataframe, load_mc_dataframe
from .bootstrap import bootstrap_ci, bootstrap_ci_dict
from .exemplar_agreement import (
    build_assignment_map,
    build_code_map,
    jaccard_overlap,
    krippendorff_alpha,
    macro_jaccard,
    ontology_weighted_disagreement,
)
from .interpretation_overlap import (
    claim_evidence_congruence,
    interpretation_theme_coherence,
)
from .report import build_json, build_markdown, build_report_dict
from .semantic_alignment import hungarian_alignment, max_pooled_hybrid_similarity

logger = get_logger(__name__)

EXIT_SUCCESS = 0
EXIT_STORAGE_CORRUPTION = 3


def _build_emb_cache(texts: set[str]) -> dict[str, np.ndarray]:
    """Generate and cache embeddings for a set of strings."""
    from semantic.embeddings import generate_embedding

    cache: dict[str, np.ndarray] = {}
    for t in texts:
        emb = generate_embedding(t)
        if emb is not None:
            cache[t] = emb.astype(np.float64)
    return cache


def _load_ontology_distances() -> dict[str, dict[str, float]]:
    """Build tag-pair distance dict from Parquet ontology."""
    try:
        from persistence.loaders import load_tags

        lf = load_tags()
        df = lf.collect()
        tags = df["tag"].to_list()
        parents = df.get_column("parent").to_list() if "parent" in df.columns else []

        children: dict[str, list[str]] = {}
        for tag, parent in zip(tags, parents):
            if parent and parent != tag:
                children.setdefault(parent, []).append(tag)
                children.setdefault(tag, [])

        dist: dict[str, dict[str, float]] = {}
        for t1 in tags:
            dist[t1] = {}
            for t2 in tags:
                if t1 == t2:
                    dist[t1][t2] = 0.0
                else:
                    visited: set[str] = set()
                    queue: list[tuple[str, int]] = [(t1, 0)]
                    found = 0.0
                    while queue:
                        node, d = queue.pop(0)
                        if node == t2:
                            found = d / max(len(tags), 1)
                            break
                        if node in visited:
                            continue
                        visited.add(node)
                        for child in children.get(node, []):
                            if child not in visited:
                                queue.append((child, d + 1))
                        try:
                            idx = tags.index(node)
                            p = parents[idx]
                            if p and p != node and p not in visited:
                                queue.append((p, d + 1))
                        except (ValueError, IndexError):
                            pass
                    dist[t1][t2] = found if found else 1.0
        return dist
    except Exception:
        logger.warning("Could not load ontology distances; using default 1.0")
        return {}


def _flatten_ci(ci: dict[str, Any]) -> float | dict[str, float]:
    """Flatten CI to raw value if no iterations, else keep dict."""
    if ci.get("n_iterations", 0) == 0:
        return float(ci.get("point_estimate", 0.0))
    return ci


def run_benchmark(
    hc_paths: list[Path],
    output_path: Path = Path("data/output/benchmark-report.json"),
    bootstrap_iterations: int = 1000,
) -> int:
    """Run the full benchmark evaluation. Returns exit code."""
    con = get_connection()
    config = Config.from_env()

    # ── 1. Load MC from DuckDB ──────────────────────────────────────────
    mc_rows = load_mc_dataframe(con, config)
    if not mc_rows:
        logger.error("No data in DuckDB. Run 'python analyze.py run' first.")
        con.close()
        return EXIT_STORAGE_CORRUPTION

    # ── 2. Load all HC dataframes ───────────────────────────────────────
    hc_data: dict[str, list[dict[str, str]]] = {}
    for path in hc_paths:
        label = path.stem.replace("benchmark-", "").upper()
        hc_data[label] = load_hc_dataframe(path)

    if not hc_data:
        logger.error("No human-coder data loaded. Check --source paths.")
        con.close()
        return EXIT_STORAGE_CORRUPTION

    # ── 3. Align all coder pairs ────────────────────────────────────────
    sources_list = [str(p) for p in hc_paths]
    all_pairs: list[tuple[str, str, list[dict], list[dict]]] = []
    common_eids: set[str] = set(mc_rows[r]["id"] for r in range(len(mc_rows)))

    for label, hc_rows in hc_data.items():
        mc_aligned, hc_aligned = align_dataframes(mc_rows, hc_rows, label)
        if mc_aligned:
            common_eids &= {r["id"] for r in mc_aligned}
            all_pairs.append(("MC", label, mc_aligned, hc_aligned))

    if len(hc_data) >= 2:
        labels = sorted(hc_data.keys())
        for i in range(len(labels)):
            for j in range(i + 1, len(labels)):
                la, lb = labels[i], labels[j]
                all_pairs.append((la, lb, hc_data[la], hc_data[lb]))

    if not all_pairs:
        logger.error("No aligned exemplars found.")
        con.close()
        return EXIT_STORAGE_CORRUPTION

    # ── 4. Pre-compute embeddings ───────────────────────────────────────
    all_names: set[str] = set()
    for _, _, ra, rb in all_pairs:
        for code in build_code_map(ra):
            all_names.add(code)
        for code in build_code_map(rb):
            all_names.add(code)
        for row in ra:
            all_names.add(row.get("theme", ""))
        for row in rb:
            all_names.add(row.get("theme", ""))

    # Add exemplar content for Level 3b
    for row in mc_rows:
        all_names.add(row["content"])

    # Add interpretation claims
    mc_interpretations: list[dict[str, Any]] = []
    try:
        from orchestration.export import _gather_approved_nodes

        _, _, mc_interpretations = _gather_approved_nodes(con)
        for interp in mc_interpretations:
            narrative = interp.get("definition", "")
            if narrative:
                import re

                for s in re.split(r"[.?!]\s+", narrative):
                    if len(s.strip()) > 20:
                        all_names.add(s.strip())
    except Exception:
        pass

    logger.info("Pre-computing embeddings", extra={"unique_texts": len(all_names)})
    emb_cache = _build_emb_cache(all_names)
    logger.info("Embedding cache built", extra={"cached": len(emb_cache)})

    # ── 5. Load ontology distances ──────────────────────────────────────
    ontology_dist = _load_ontology_distances()

    # ── 6. Run all metrics ──────────────────────────────────────────────
    level1: dict[str, Any] = {
        "macro_jaccard": {},
        "krippendorff_alpha": {},
        "ontology_weighted_disagreement": {},
        "jaccard_per_code": {},
    }
    level2: dict[str, Any] = {
        "max_pooled_macro_avg": {},
        "hungarian": {"mean_weight": {}, "fraction_unmatched": {}},
    }
    level3: dict[str, Any] = {}

    for label_a, label_b, rows_a, rows_b in all_pairs:
        pair_key = f"{label_a}_{label_b}"

        # ── Level 1a: Jaccard ───────────────────────────────────────────
        def _jaccard_fn(ra: list[dict], rb: list[dict], **kw: Any) -> float:
            return macro_jaccard(build_code_map(ra), build_code_map(rb))

        level1["macro_jaccard"][pair_key] = _flatten_ci(
            bootstrap_ci(_jaccard_fn, rows_a, rows_b, n_iterations=bootstrap_iterations)
        )

        # Per-code Jaccard detail (no bootstrap)
        per_code = {
            code: float(jac)
            for code, jac in sorted(
                jaccard_overlap(build_code_map(rows_a), build_code_map(rows_b)).items()
            )
        }
        level1.setdefault("jaccard_per_code", {})[pair_key] = per_code

        # ── Level 1b: Krippendorff's alpha ──────────────────────────────
        def _alpha_fn(ra: list[dict], rb: list[dict], **kw: Any) -> float:
            return krippendorff_alpha(
                build_assignment_map(ra), build_assignment_map(rb)
            )

        level1["krippendorff_alpha"][pair_key] = _flatten_ci(
            bootstrap_ci(_alpha_fn, rows_a, rows_b, n_iterations=bootstrap_iterations)
        )

        # ── Level 1c: Ontology-weighted disagreement ────────────────────
        def _ont_fn(ra: list[dict], rb: list[dict], **kw: Any) -> dict[str, float]:
            return ontology_weighted_disagreement(
                {r["id"]: r for r in ra},
                {r["id"]: r for r in rb},
                ontology_dist,
            )

        level1["ontology_weighted_disagreement"][pair_key] = _flatten_ci(
            bootstrap_ci_dict(
                _ont_fn, rows_a, rows_b, n_iterations=bootstrap_iterations
            )
        )

        # ── Level 2a: Max-pooled hybrid similarity ──────────────────────
        def _hybrid_fn(ra: list[dict], rb: list[dict], **kw: Any) -> float:
            cm_a = build_code_map(ra)
            cm_b = build_code_map(rb)
            res = max_pooled_hybrid_similarity(cm_a, cm_b, emb_cache)
            return float(res.get("_macro_avg", 0.0))

        level2["max_pooled_macro_avg"][pair_key] = _flatten_ci(
            bootstrap_ci(_hybrid_fn, rows_a, rows_b, n_iterations=bootstrap_iterations)
        )

        # ── Level 2b: Hungarian ─────────────────────────────────────────
        def _hung_mean_fn(ra: list[dict], rb: list[dict], **kw: Any) -> float:
            res = hungarian_alignment(build_code_map(ra), build_code_map(rb), emb_cache)
            return float(res["mean_weight"])

        def _hung_unmatched_fn(ra: list[dict], rb: list[dict], **kw: Any) -> float:
            res = hungarian_alignment(build_code_map(ra), build_code_map(rb), emb_cache)
            return float(res["fraction_unmatched"])

        level2["hungarian"]["mean_weight"][pair_key] = _flatten_ci(
            bootstrap_ci(
                _hung_mean_fn,
                rows_a,
                rows_b,
                n_iterations=bootstrap_iterations,
            )
        )
        level2["hungarian"]["fraction_unmatched"][pair_key] = _flatten_ci(
            bootstrap_ci(
                _hung_unmatched_fn,
                rows_a,
                rows_b,
                n_iterations=bootstrap_iterations,
            )
        )

    # ── Level 3: MC-only metrics ────────────────────────────────────────
    if mc_rows:

        def _coh_fn(ra: list[dict], rb: list[dict], **kw: Any) -> float:
            res = interpretation_theme_coherence(ra, emb_cache)
            return float(res.get("_macro_avg", 0.0))

        level3["interpretation_theme_coherence"] = {
            "_macro_avg": _flatten_ci(
                bootstrap_ci(
                    _coh_fn,
                    mc_rows,
                    mc_rows,
                    n_iterations=bootstrap_iterations,
                )
            ),
        }
        try:
            per_interp = interpretation_theme_coherence(mc_rows, emb_cache)
            for k, v in per_interp.items():
                if k != "_macro_avg":
                    level3["interpretation_theme_coherence"][k] = float(v)
        except Exception:
            pass

        def _ce_fn(ra: list[dict], rb: list[dict], **kw: Any) -> float:
            res = claim_evidence_congruence(ra, mc_interpretations, emb_cache=emb_cache)
            v = res.get("_macro_avg", {})
            if isinstance(v, dict):
                return float(v.get("mean_congruence", 0.0))
            return float(v)

        level3["claim_evidence_congruence"] = {
            "_macro_avg": _flatten_ci(
                bootstrap_ci(
                    _ce_fn,
                    mc_rows,
                    mc_rows,
                    n_iterations=bootstrap_iterations,
                )
            ),
        }

    # ── 7. Assemble and write report ────────────────────────────────────
    report = build_report_dict(
        date=datetime.now(timezone.utc).isoformat(),
        sources=sources_list,
        common_exemplar_count=len(common_eids),
        bootstrap_iterations=bootstrap_iterations,
        level1=level1,
        level2=level2,
        level3=level3,
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    _write_report(report, output_path)

    con.close()
    logger.info("Benchmark complete", extra={"output": str(output_path)})
    return EXIT_SUCCESS


def _write_report(report: dict[str, Any], output_path: Path) -> None:
    """Write JSON and Markdown report files."""
    from utils.atomic_io import write_json, write_markdown

    write_json(build_json(report), output_path)
    md_path = output_path.with_suffix(".md")
    write_markdown(build_markdown(report), md_path)
    click.echo(f"Benchmark report written to {output_path}")
    click.echo(f"Markdown summary written to {md_path}")


# ── CLI subcommand ──────────────────────────────────────────────────────


@click.command("benchmark")
@click.option(
    "--source",
    "sources",
    type=click.Path(exists=True, dir_okay=False, resolve_path=True),
    multiple=True,
    required=True,
    help="Path to a human-coder benchmark CSV. Repeatable.",
)
@click.option(
    "--output",
    default="data/output/benchmark-report.json",
    type=click.Path(dir_okay=False, resolve_path=True),
    help="Output path for the benchmark report JSON.",
)
@click.option(
    "--bootstrap",
    default=1000,
    type=int,
    show_default=True,
    help="Number of bootstrap iterations for CIs. 0 to skip.",
)
def benchmark_cmd(
    sources: tuple[str, ...],
    output: str,
    bootstrap: int,
) -> None:
    """Compare machine-coded output against human-coded benchmarks.

    Runs three-level evaluation on exemplar-to-code allocation, code
    and theme semantic alignment, and interpretation coherence.
    """
    hc_paths = [Path(s) for s in sources]
    exit_code = run_benchmark(
        hc_paths=hc_paths,
        output_path=Path(output),
        bootstrap_iterations=bootstrap,
    )
    sys.exit(exit_code)
