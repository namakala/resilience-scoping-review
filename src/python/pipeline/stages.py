"""Stage-to-Hamilton-final-vars mapping for the pipeline executor.

Each workflow stage (1-10) maps to its own terminal output nodes.  The
executor builds cumulative lists (stage N = stage 1 + ... + stage N) so
that result dicts are self-contained for downstream orchestration.
"""

from __future__ import annotations

_STAGE_OWN_VARS: dict[int, list[str]] = {
    1: [
        "load_exemplars",
        "load_tags",
        "load_keywords",
        "extract_keywords",
        "resolve_tag_dag",
        "validate_artifact_schemas",
        "compute_exemplar_statistics",
        "prepare_artifact_summary",
    ],
    2: [
        "cache_exemplar_embeddings",
        "cache_keyword_embeddings",
        "verify_embedding_integrity",
    ],
    3: [
        "build_ontology_graph",
        "build_bm25",
        "materialize_traversal_cache",
        "validate_ontology_constraints",
        "build_tag_scope_index",
        "compute_ontology_statistics",
        "build_combined_index_metadata",
    ],
    4: [
        "infer_codes",
        "prepare_code_nodes",
        "retrieve_code_candidates",
        "build_query_context",
        "rank_exemplar_candidates",
        "format_retrieval_for_inference",
        "compute_retrieval_statistics",
    ],
    5: [
        "review_codes",
        "apply_code_edits",
    ],
    6: [
        "infer_themes",
        "prepare_theme_nodes",
        "embed_codes",
        "retrieve_theme_candidates",
    ],
    7: [
        "review_themes",
        "apply_theme_edits",
    ],
    8: [
        "infer_interpretations",
        "prepare_interpretation_nodes",
        "embed_themes",
        "retrieve_interpretation_candidates",
    ],
    9: [
        "review_interpretations",
        "apply_interpretation_edits",
    ],
    10: [
        "export_codes",
        "export_themes",
        "export_interpretations",
        "export_combined",
        "export_summary",
    ],
}


def _build_cumulative_vars(stage: int) -> list[str]:
    """Concatenate each stage's own vars for stages 1 through *stage*."""
    result: list[str] = []
    for s in range(1, stage + 1):
        result.extend(_STAGE_OWN_VARS[s])
    return result


def get_final_vars_for_stage(stage: int) -> list[str]:
    """Return cumulative output nodes for workflow stage *stage* (1-10).

    Each stage includes all prior stages' outputs so the result dict is
    self-contained for the orchestration layer.
    """
    if stage not in _STAGE_OWN_VARS:
        raise ValueError(f"Unknown stage: {stage}. Valid stages: 1-10")
    return _build_cumulative_vars(stage)
