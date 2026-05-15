"""Data types for DAG execution tracking.

Defines ``NodeExecutionRecord`` (outcome of one DAG node),
``ExecutionResult`` (output of ``execute_dag()``), and the
``get_execution_summary()`` convenience aggregator.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


@dataclass
class NodeExecutionRecord:
    """Outcome for one DAG node: executed / overridden / cached / skipped."""

    node_name: str
    status: Literal["executed", "overridden", "cached", "skipped"]
    duration_ms: float = 0.0
    error: str | None = None


@dataclass
class ExecutionResult:
    """Result of ``execute_dag()`` — outputs plus per-node execution records."""

    outputs: dict[str, Any]
    node_executions: list[NodeExecutionRecord] = field(default_factory=list)
    total_duration_ms: float = 0.0
    stage: int | None = None
    cache_hit_count: int = 0
    cache_miss_count: int = 0


def get_execution_summary(result: ExecutionResult) -> dict[str, Any]:
    """Aggregate execution counts and cache-hit rate for CLI reporting."""
    counts: dict[str, int] = {
        "executed": 0,
        "overridden": 0,
        "cached": 0,
        "skipped": 0,
    }
    for rec in result.node_executions:
        counts[rec.status] = counts.get(rec.status, 0) + 1
    total = sum(counts.values())
    hit_rate = (
        result.cache_hit_count / (result.cache_hit_count + result.cache_miss_count)
        if (result.cache_hit_count + result.cache_miss_count) > 0
        else 0.0
    )
    return {
        **counts,
        "total_nodes": total,
        "total_duration_ms": result.total_duration_ms,
        "stage": result.stage,
        "cache_hit_rate": hit_rate,
    }
