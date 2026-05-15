"""Stage-transition driver — main pipeline loop.

Drives the workflow through stages 1-10: execute DAG → checkpoint →
HITL if review stage → advance.  Handles Ctrl-C via graceful_shutdown
and loads real dirty_flags from state for selective recomputation.
"""

from __future__ import annotations

import time
from typing import Any

import duckdb
from hamilton.driver import Driver
from orchestration.state import WorkflowState
from orchestration.state_rules import MAX_STAGE
from persistence.state_repository import save_state
from pipeline.cache_adapter import CacheMetrics, NodeCacheAdapter
from pipeline.config import Config
from pipeline.constructor import create_pipeline
from pipeline.executor import execute_dag
from pipeline.types import ExecutionResult
from utils.graceful_shutdown import graceful_shutdown
from utils.logging import get_logger

logger = get_logger(__name__)

STAGE_NAMES: dict[int, str] = {
    1: "load",
    2: "embed",
    3: "index",
    4: "infer_codes",
    5: "review_codes",
    6: "infer_themes",
    7: "review_themes",
    8: "infer_interpretations",
    9: "review_interpretations",
    10: "export",
}

REVIEW_STAGES: frozenset[int] = frozenset({5, 7, 9})

TYPE_TO_TARGET_STAGE: dict[str, int] = {
    "code": 5,
    "theme": 7,
    "interpretation": 9,
}


def resolve_target_stage(types: tuple[str, ...]) -> int:
    """Map artifact type(s) to the highest completion stage.

    Empty tuple means all stages (target=10).
    """
    if not types:
        return MAX_STAGE
    return max(TYPE_TO_TARGET_STAGE[t] for t in types)


def run_pipeline(
    con: duckdb.DuckDBPyConnection,
    state: WorkflowState,
    config: Config,
    target_stage: int = MAX_STAGE,
) -> WorkflowState:
    """Drive the pipeline from ``state.current_stage`` through ``target_stage``.

    Each iteration: execute DAG for current stage → save checkpoint →
    HITL review if review stage → advance.  Ctrl-C saves checkpoint and exits.
    """
    if state.current_stage > target_stage:
        logger.info(
            "Already past target stage %d (current=%d); nothing to do",
            target_stage,
            state.current_stage,
        )
        return state

    metrics = CacheMetrics()
    adapter = NodeCacheAdapter(con, metrics)
    builder = create_pipeline(config, adapters=[adapter])
    driver = builder.build()

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
            result = execute_stage(driver, stage, con, state, metrics)
            elapsed = time.monotonic() - start

            executed = sum(1 for n in result.node_executions if n.status == "executed")
            cached = sum(1 for n in result.node_executions if n.status == "cached")

            failure_count = sum(
                1 for n in result.node_executions if n.status == "skipped" and n.error
            )

            logger.info(
                "Stage %d (%s) completed in %.1fs",
                stage,
                stage_name,
                elapsed,
                extra={
                    "stage": stage,
                    "stage_name": stage_name,
                    "duration_s": round(elapsed, 1),
                    "nodes_executed": executed,
                    "nodes_cached": cached,
                    "failures": failure_count,
                },
            )

            _save_checkpoint(con, state)

            if stage in REVIEW_STAGES:
                from orchestration.hitl_coordinator import coordinate_hitl
                from persistence.duckdb_connection import DEFAULT_DB_PATH

                state = coordinate_hitl(con, stage, state, DEFAULT_DB_PATH)

            if stage == MAX_STAGE:
                from orchestration.export import export_all
                from persistence.duckdb_connection import DEFAULT_DB_PATH

                export_all(con, state, config, DEFAULT_DB_PATH)
                break
            state.advance_stage()

    return state


def execute_stage(
    driver: Driver,
    stage: int,
    con: duckdb.DuckDBPyConnection,
    state: WorkflowState,
    cache_metrics: CacheMetrics,
) -> ExecutionResult:
    """Execute all DAG nodes required for *stage*.

    Loads dirty_flags from state for selective recomputation
    (inference stages 4/6/8).  Non-dirty stages get None.
    """
    inference_stages = {4, 6, 8}
    dirty_flags: dict[str, bool] | None = (
        dict(state.dirty_flags) if stage in inference_stages else None
    )
    inputs: dict[str, Any] = {}
    if dirty_flags:
        inputs["dirty_flags"] = dirty_flags

    return execute_dag(
        driver,
        stage=stage,
        inputs=inputs or None,
        cache_metrics=cache_metrics,
    )


# ── Private helpers ─────────────────────────────────────────────────────────


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
    "execute_stage",
    "resolve_target_stage",
    "STAGE_NAMES",
    "REVIEW_STAGES",
    "TYPE_TO_TARGET_STAGE",
    "MAX_STAGE",
]
