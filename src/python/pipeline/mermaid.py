"""Mermaid DAG rendering for Hamilton pipelines.

Extracted from ``wiring.py`` to keep each module under 200 lines.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from hamilton.driver import Driver

EXTERNAL_INPUTS = frozenset(
    {"config", "existing_codes", "existing_theme_nodes", "tag_metadata"}
)

_NODE_PREFIX_CLUSTER: list[tuple[str, str]] = [
    ("validate_artifact", "Artifacts"),
    ("compute_exemplar", "Artifacts"),
    ("prepare_artifact", "Artifacts"),
    ("load_", "Artifacts"),
    ("resolve_tag_dag", "Artifacts"),
    ("init_embedding", "Embedding"),
    ("cache_", "Embedding"),
    ("verify_embedding", "Embedding"),
    ("embed_", "Embedding"),
    ("build_bm25", "Index"),
    ("build_ontology_graph", "Index"),
    ("build_ontology", "Index"),
    ("build_combined", "Index"),
    ("build_tag_scope", "Index"),
    ("materialize_", "Index"),
    ("compute_ontology", "Index"),
    ("validate_ontology", "Index"),
    ("retrieve_", "Retrieval"),
    ("rank_", "Retrieval"),
    ("build_query_context", "Retrieval"),
    ("format_retrieval", "Retrieval"),
    ("compute_retrieval", "Retrieval"),
    ("init_groq", "Inference"),
    ("prepare_code", "Inference"),
    ("prepare_theme", "Inference"),
    ("prepare_interpretation", "Inference"),
    ("infer_", "Inference"),
    ("review_", "Review"),
    ("apply_code", "Review"),
    ("apply_theme", "Review"),
    ("apply_interpretation", "Review"),
    ("export_", "Export"),
]


def _cluster_name(node_name: str) -> str:
    for prefix, cluster in _NODE_PREFIX_CLUSTER:
        if node_name.startswith(prefix):
            return cluster
    return "Other"


def _safe_name(node_name: str) -> str:
    return node_name.replace("-", "_").replace(".", "_")


def render_dag_mermaid(
    driver: Driver,
    output_path: str | Path,
    *,
    final_vars: list[str] | None = None,
    overrides: dict[str, Any] | None = None,
    direction: str = "TD",
) -> str:
    """Render the DAG as a Mermaid flowchart and write to *output_path*.

    Parameters
    ----------
    driver :
        Built Hamilton driver.
    output_path :
        Destination for the ``.mmd`` file.
    final_vars :
        When provided, only nodes relevant to computing *final_vars* are
        included (subgraph pruning).
    overrides :
        Node names in this dict are styled with dashed borders.
    direction :
        Mermaid flowchart direction (``"TD"``, ``"LR"``, ``"BT"``, ``"RL"``).

    Returns
    -------
    str
        The Mermaid source text (also written to *output_path*).
    """
    overrides_set = set(overrides or {})

    if final_vars:
        relevant_names: set[str] = set()
        for target in final_vars:
            upstream_set, _ = driver.graph.get_upstream_nodes([target])
            relevant_names.add(target)
            for n in upstream_set:
                relevant_names.add(n.name)
    else:
        relevant_names = {n.name for n in driver.graph.get_nodes()}

    nodes = [n for n in driver.graph.get_nodes() if n.name in relevant_names]

    clusters: dict[str, list[str]] = {}
    for node in nodes:
        name = node.name
        if name in EXTERNAL_INPUTS:
            continue
        group = _cluster_name(name)
        clusters.setdefault(group, []).append(name)

    lines: list[str] = []
    lines.append(f"flowchart {direction}")
    lines.append("")

    for group, members in sorted(clusters.items()):
        safe_group = _safe_name(group)
        lines.append(f'  subgraph {safe_group}["{group}"]')
        for m_name in sorted(members):
            safe = _safe_name(m_name)
            lines.append(f'    {safe}["{m_name}"]')
        lines.append("  end")
        lines.append("")

    external_present = [n for n in EXTERNAL_INPUTS if n in relevant_names]
    if external_present:
        lines.append('  subgraph Inputs["External Inputs"]')
        for name in sorted(external_present):
            lines.append(f'    {name}("{name}")')
        lines.append("  end")
        lines.append("")

    for node in nodes:
        name = node.name
        if name in EXTERNAL_INPUTS:
            continue
        safe = _safe_name(name)
        for dep_name in node.input_types:
            if dep_name in EXTERNAL_INPUTS:
                safe_dep = dep_name
            elif dep_name not in relevant_names:
                continue
            else:
                safe_dep = _safe_name(dep_name)
            if name in overrides_set:
                lines.append(f"  {safe_dep}-.->|override|{safe}")
            else:
                lines.append(f"  {safe_dep}-->{safe}")

    mermaid_source = "\n".join(lines) + "\n"
    Path(output_path).write_text(mermaid_source, encoding="utf-8")
    return mermaid_source
