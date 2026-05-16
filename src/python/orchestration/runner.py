"""Stage-transition driver — sequential pipeline loop.

Drives the workflow through stages 1-10: load → embed → index →
infer codes → HITL → infer themes → HITL → synthesize interpretations
→ HITL → export.  Tag-level dirty-flag gating for theme inference
minimizes LLM API calls.
"""

from __future__ import annotations

import time

import duckdb
from config.config import Config
from orchestration.state import WorkflowState
from orchestration.state_rules import MAX_STAGE, STAGE_NAMES
from persistence.state_repository import save_state
from utils.graceful_shutdown import graceful_shutdown
from utils.logging import get_logger

logger = get_logger(__name__)

REVIEW_STAGES: frozenset[int] = frozenset({5, 7, 9})

TYPE_TO_TARGET_STAGE: dict[str, int] = {
    "code": 5,
    "theme": 7,
    "interpretation": 9,
}


def resolve_target_stage(types: tuple[str, ...]) -> int:
    """Map artifact type(s) to the highest review-completion stage."""
    if not types:
        return MAX_STAGE
    return max(TYPE_TO_TARGET_STAGE[t] for t in types)


def _select_limited_tags(limit: int) -> list[str]:
    """Return the top *limit* tags with the most exemplars (n_contents > 0).

    Sorted by ``n_contents`` descending, then alphabetically for
    determinism.  Caller must ensure *limit* > 0.
    """
    from ontology.dag import get_tag_dag

    G = get_tag_dag()
    candidates: list[tuple[str, int]] = [
        (n, G.nodes[n].get("n_contents", 0))
        for n in G.nodes
        if G.nodes[n].get("n_contents", 0) > 0
    ]
    candidates.sort(key=lambda x: (-x[1], x[0]))
    selected = [t[0] for t in candidates[:limit]]
    logger.info(
        "Selected %d tag(s) for limited processing: %s",
        len(selected),
        selected,
        extra={"limit": limit, "available": len(candidates)},
    )
    return selected


def run_pipeline(
    con: duckdb.DuckDBPyConnection,
    state: WorkflowState,
    config: Config,
    target_stage: int = MAX_STAGE,
    limit: int = 0,
) -> WorkflowState:
    if state.current_stage > target_stage:
        logger.info(
            "Already past target stage %d (current=%d); nothing to do",
            target_stage,
            state.current_stage,
        )
        return state

    limited_tags: list[str] | None = _select_limited_tags(limit) if limit > 0 else None

    def _checkpoint() -> None:
        _save_checkpoint(con, state)

    with graceful_shutdown(_checkpoint):
        while state.current_stage <= target_stage:
            stage = state.current_stage
            stage_name = STAGE_NAMES.get(stage, f"stage_{stage}")

            logger.info(
                "Stage %d (%s) started",
                stage,
                stage_name,
                extra={"stage": stage, "stage_name": stage_name},
            )

            start = time.monotonic()

            if stage == 1:
                _run_stage_load(con, config)
            elif stage == 2:
                _run_stage_embed(con)
            elif stage == 3:
                _run_stage_index(con, config)
            elif stage == 4:
                _run_stage_infer_codes(con, limited_tags=limited_tags)
            elif stage == 5:
                state = _run_stage_review_codes(con, state)
            elif stage == 6:
                _run_stage_infer_themes(con, state, limited_tags=limited_tags)
            elif stage == 7:
                state = _run_stage_review_themes(con, state)
            elif stage == 8:
                _run_stage_synthesize_interpretations(con, limited_tags=limited_tags)
            elif stage == 9:
                state = _run_stage_review_interpretations(con, state)
            elif stage == 10:
                _run_stage_export(con, state, config)
                break

            elapsed = time.monotonic() - start
            logger.info(
                "Stage %d (%s) completed in %.1fs",
                stage,
                stage_name,
                elapsed,
                extra={
                    "stage": stage,
                    "stage_name": stage_name,
                    "duration_s": round(elapsed, 1),
                },
            )

            _save_checkpoint(con, state)
            state.advance_stage()

    from inference.llm_logger import flush_llm_log

    flush_llm_log(config.export_output_path / "llm_output.json")
    return state


# ── Stage runners ──────────────────────────────────────────────────────────


def _run_stage_load(con: duckdb.DuckDBPyConnection, config: Config) -> None:
    """Load exemplars and tags from Parquet, extract keywords, validate schemas."""
    from persistence.loaders import load_exemplars, load_keywords, load_tags

    _ = load_exemplars()
    _ = load_tags()
    _ = load_keywords()

    from semantic.keyword_extraction import extract_keywords

    extract_keywords(con)

    from ontology.dag import build_tag_dag, validate_tag_dag

    G = build_tag_dag()
    validate_tag_dag(G)

    logger.info("Data load and validation complete")


def _run_stage_embed(con: duckdb.DuckDBPyConnection) -> None:
    """Generate embeddings for uncached exemplars and keywords."""
    from semantic.embedding_generation import generate_exemplar_embeddings
    from semantic.keyword_embedding import generate_keyword_embeddings

    generate_exemplar_embeddings(con)
    generate_keyword_embeddings(con)

    logger.info("Embedding generation complete")


def _run_stage_index(con: duckdb.DuckDBPyConnection, config: Config) -> None:
    """Build BM25 index, ontology graph traversal cache."""
    from persistence.loaders import load_keywords
    from semantic.index_builder import build_index

    kw_lf = load_keywords()
    build_index(kw_lf, tokenizer_config=config.bm25_tokenizer_config)

    from ontology.cache import build_traversal_cache

    build_traversal_cache()

    logger.info("Index build complete")


def _run_stage_infer_codes(
    con: duckdb.DuckDBPyConnection,
    limited_tags: list[str] | None = None,
) -> None:
    """Seed inference_status, then infer codes from pending exemplars.

    The seed step ensures the ``inference_status`` table contains a
    ``pending`` row for every exemplar so that code inference finds them.
    It runs here, between indexing (stage 3) and inference (stage 4),
    and is idempotent (``INSERT OR IGNORE``).

    When *limited_tags* is provided, only those tags are processed.
    """
    from inference.seed_inference_status import seed_pending_exemplars

    seed_pending_exemplars(con)

    from inference.code_inference import infer_codes

    codes = infer_codes(con, tags=limited_tags)
    if codes:
        from inference.code_node_creation import create_code_nodes
        from persistence.duckdb_connection import DEFAULT_DB_PATH

        create_code_nodes(con, codes, db_path=DEFAULT_DB_PATH)


def _run_stage_review_codes(
    con: duckdb.DuckDBPyConnection,
    state: WorkflowState,
) -> WorkflowState:
    """HITL review of inferred codes."""
    from orchestration.hitl_coordinator import coordinate_hitl

    return coordinate_hitl(con, 5, state)


def _run_stage_infer_themes(
    con: duckdb.DuckDBPyConnection,
    state: WorkflowState,
    limited_tags: list[str] | None = None,
) -> None:
    """Infer themes only for tags with dirty flags set.

    Tags with dirty=False are skipped entirely — zero LLM calls.
    When *limited_tags* is provided, only those tags are considered
    (intersection of dirty and limited).
    """
    from inference.theme_inference import infer_themes

    for tag, is_dirty in state.dirty_flags.items():
        if is_dirty and (limited_tags is None or tag in limited_tags):
            themes = infer_themes(con, tag=tag)
            if themes:
                from inference.create_theme_nodes import create_theme_nodes
                from persistence.duckdb_connection import DEFAULT_DB_PATH

                create_theme_nodes(con, themes, tag=tag, db_path=DEFAULT_DB_PATH)
        else:
            logger.debug("Skipping clean tag '%s' for theme inference", tag)


def _run_stage_review_themes(
    con: duckdb.DuckDBPyConnection,
    state: WorkflowState,
) -> WorkflowState:
    """HITL review of inferred themes."""
    from orchestration.hitl_coordinator import coordinate_hitl

    return coordinate_hitl(con, 7, state)


def _run_stage_synthesize_interpretations(
    con: duckdb.DuckDBPyConnection,
    limited_tags: list[str] | None = None,
) -> None:
    """Synthesize interpretations from approved themes.

    When *limited_tags* is provided, only those tags are considered.
    """
    from inference.interpretation_synthesis import synthesize_interpretations

    interpretations = synthesize_interpretations(con, tags=limited_tags)
    if interpretations:
        from inference.interpretation_creation import create_interpretation_nodes
        from persistence.duckdb_connection import DEFAULT_DB_PATH

        create_interpretation_nodes(con, interpretations, db_path=DEFAULT_DB_PATH)


def _run_stage_review_interpretations(
    con: duckdb.DuckDBPyConnection,
    state: WorkflowState,
) -> WorkflowState:
    """HITL review of synthesized interpretations."""
    from orchestration.hitl_coordinator import coordinate_hitl

    return coordinate_hitl(con, 9, state)


def _run_stage_export(
    con: duckdb.DuckDBPyConnection,
    state: WorkflowState,
    config: Config,
) -> None:
    """Export approved results to JSON, CSV, and Markdown."""
    from orchestration.export import export_all
    from persistence.duckdb_connection import DEFAULT_DB_PATH

    export_all(con, state, config, DEFAULT_DB_PATH)


# ── Checkpoint ─────────────────────────────────────────────────────────────


def _save_checkpoint(con: duckdb.DuckDBPyConnection, state: WorkflowState) -> None:
    """Persist the current workflow state to DuckDB."""
    from datetime import datetime, timezone

    state.last_checkpoint = datetime.now(timezone.utc).isoformat()
    save_state(con, state.to_state_dict())
    logger.debug(
        "Checkpoint saved",
        extra={"stage": state.current_stage, "checkpoint": state.last_checkpoint},
    )


__all__ = [
    "run_pipeline",
    "resolve_target_stage",
    "STAGE_NAMES",
    "REVIEW_STAGES",
    "TYPE_TO_TARGET_STAGE",
    "MAX_STAGE",
]
