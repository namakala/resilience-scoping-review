"""DAG execution with selective node computation, stage awareness, and logging.

Wraps Hamilton's ``Driver.execute()`` with dirty-flag integration, per-node
execution tracking (``NODE START`` / ``NODE FINISH``), and stage-aware
``final_vars`` resolution.

References:
    ADR-008 (Pipeline Orchestration): Hamilton DAG as execution engine
    ADR-007 (Incremental Ontology Evolution): dirty-flag selective execution
"""

from __future__ import annotations

import time
from typing import Any

from hamilton.driver import Driver
from pipeline.stages import get_final_vars_for_stage
from pipeline.types import ExecutionResult, NodeExecutionRecord
from pipeline.wiring import EXTERNAL_INPUTS
from utils.logging import get_logger

logger = get_logger(__name__)


def execute_dag(
    driver: Driver,
    *,
    final_vars: list[str] | None = None,
    stage: int | None = None,
    inputs: dict[str, Any] | None = None,
    overrides: dict[str, Any] | None = None,
) -> ExecutionResult:
    """Execute the Hamilton DAG with node-level logging and dirty-flag selectivity.

    Either ``final_vars`` or ``stage`` is required (mutually exclusive).
    When ``stage`` is given, cumulative ``final_vars`` are resolved via
    :func:`get_final_vars_for_stage`.  ``overrides`` prevent Hamilton from
    computing those nodes (used for HITL approvals, mocks, and
    ``{"current_stage": N}`` for stage resumption).
    """
    if final_vars is None and stage is None:
        raise ValueError("Either final_vars or stage must be provided")
    if final_vars is not None and stage is not None:
        raise ValueError("Only one of final_vars or stage may be provided")
    if stage is not None:
        final_vars = get_final_vars_for_stage(stage)

    # At this point final_vars is guaranteed non-None (one of the two
    # mandatory arguments was provided and validated above).
    assert final_vars is not None

    resolved_inputs = dict(inputs or {})
    resolved_overrides = dict(overrides or {})
    expected_nodes = _resolve_execution_plan(driver, final_vars, resolved_overrides)

    for node_name in expected_nodes:
        if node_name in resolved_overrides:
            logger.info("NODE OVERRIDDEN", extra={"node": node_name, "stage": stage})
        else:
            logger.info("NODE START", extra={"node": node_name, "stage": stage})

    start = time.monotonic()
    try:
        outputs: dict[str, Any] = driver.execute(
            final_vars=final_vars,
            inputs=resolved_inputs,
            overrides=resolved_overrides,
        )
    except Exception as exc:
        total_ms = (time.monotonic() - start) * 1000
        logger.error(
            "DAG execution failed",
            extra={"stage": stage, "duration_ms": total_ms, "error": str(exc)},
        )
        return ExecutionResult(
            outputs={},
            node_executions=[
                NodeExecutionRecord(n, "skipped", error=str(exc))
                for n in expected_nodes
            ],
            total_duration_ms=total_ms,
            stage=stage,
        )
    total_ms = (time.monotonic() - start) * 1000

    records = _build_execution_records(expected_nodes, resolved_overrides, outputs)

    for rec in records:
        if rec.status == "executed":
            logger.info(
                "NODE FINISH",
                extra={
                    "node": rec.node_name,
                    "duration_ms": rec.duration_ms,
                    "stage": stage,
                },
            )

    return ExecutionResult(
        outputs=outputs,
        node_executions=records,
        total_duration_ms=total_ms,
        stage=stage,
    )


# ── Internal helpers ────────────────────────────────────────────────────────


def _resolve_execution_plan(
    driver: Driver,
    final_vars: list[str],
    overrides: dict[str, Any],
) -> list[str]:
    """Enumerate DAG nodes in the transitive dependency graph of *final_vars*.

    Excludes external inputs (``EXTERNAL_INPUTS``).  Overridden nodes remain
    in the plan so the caller can produce ``status="overridden"`` records.
    """
    upstream_set: set[str] = set()
    for fv in final_vars:
        try:
            upstream_nodes, _ = driver.graph.get_upstream_nodes([fv])
            upstream_set.update(n.name for n in upstream_nodes)
        except Exception:
            logger.warning(
                "Could not resolve upstream nodes for final_var",
                extra={"final_var": fv},
            )
    upstream_set.update(final_vars)
    upstream_set -= EXTERNAL_INPUTS
    all_nodes = {n.name: n for n in driver.graph.get_nodes()}
    return [name for name in all_nodes if name in upstream_set]


def _build_execution_records(
    expected_nodes: list[str],
    overrides: dict[str, Any],
    outputs: dict[str, Any],
) -> list[NodeExecutionRecord]:
    """Classify each expected node as overridden, executed, or skipped."""
    records: list[NodeExecutionRecord] = []
    for node_name in expected_nodes:
        if node_name in overrides:
            records.append(NodeExecutionRecord(node_name, "overridden"))
        elif node_name in outputs:
            records.append(NodeExecutionRecord(node_name, "executed"))
        else:
            records.append(NodeExecutionRecord(node_name, "skipped"))
    return records
