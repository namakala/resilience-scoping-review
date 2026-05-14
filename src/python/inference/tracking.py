"""Token usage tracking for Groq API calls.

Tracks tokens, accumulates session totals, estimates costs, warns on
excess stage cost, exposes sliding-window rate-limit awareness.
"""

import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from config import (
    max_stage_cost_usd,
    token_cost_input_per_million,
    token_cost_output_per_million,
)
from utils.logging import get_logger

from .tracking_types import UsageRecord

logger = get_logger(__name__)

_TOKEN_USAGE_LOG = Path("data/output/token_usage.log")

__all__ = [
    "TokenTracker",
    "UsageRecord",
    "format_stage_summary",
    "get_tracker",
    "reset_tracker",
]


def _compute_cost(input_tokens: int, output_tokens: int) -> float:
    """Calculate estimated cost in USD for given token counts."""
    return (
        input_tokens / 1_000_000 * token_cost_input_per_million()
        + output_tokens / 1_000_000 * token_cost_output_per_million()
    )


class TokenTracker:
    """In-memory accumulator for token usage across pipeline stages.

    Records :class:`UsageRecord` entries, maintains per-stage totals,
    supports sliding-window queries for rate-limit awareness.
    Not thread-safe; pipeline is single-threaded.
    """

    def __init__(self) -> None:
        self._records: list[UsageRecord] = []
        self._stage_totals: dict[str, dict[str, int]] = {}
        self._stage_cost_warnings: set[str] = set()

    def record(
        self,
        stage: str,
        batch_id: str,
        input_tokens: int,
        output_tokens: int,
    ) -> UsageRecord:
        """Record token usage for one LLM call.

        Writes a JSON line to ``token_usage.log``, updates the in-memory
        accumulator, and logs a warning if the stage total cost exceeds
        the configured threshold.
        """
        cost = _compute_cost(input_tokens, output_tokens)
        record = UsageRecord(
            stage=stage,
            batch_id=batch_id,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=round(cost, 6),
        )
        self._records.append(record)
        stage_acc = self._stage_totals.setdefault(stage, {"input": 0, "output": 0})
        stage_acc["input"] += input_tokens
        stage_acc["output"] += output_tokens
        self._write_log_entry(record)
        self._check_stage_cost_warning(stage, stage_acc)
        return record

    def _check_stage_cost_warning(self, stage: str, stage_acc: dict[str, int]) -> None:
        """Log warning if stage cost exceeds configured threshold."""
        threshold = max_stage_cost_usd()
        stage_cost = _compute_cost(stage_acc["input"], stage_acc["output"])
        if stage_cost > threshold and stage not in self._stage_cost_warnings:
            self._stage_cost_warnings.add(stage)
            logger.warning(
                "Stage %s cost $%.4f exceeds threshold $%.2f",
                stage,
                stage_cost,
                threshold,
                extra={
                    "stage": stage,
                    "stage_cost": round(stage_cost, 6),
                    "threshold": threshold,
                    "input_tokens": stage_acc["input"],
                    "output_tokens": stage_acc["output"],
                },
            )

    @staticmethod
    def _write_log_entry(record: UsageRecord) -> None:
        """Append a JSON line to ``token_usage.log``."""
        try:
            _TOKEN_USAGE_LOG.parent.mkdir(parents=True, exist_ok=True)
            with open(_TOKEN_USAGE_LOG, "a") as f:
                f.write(json.dumps(asdict(record), ensure_ascii=False) + "\n")
        except OSError as exc:
            logger.error(
                "Failed to write token usage log",
                extra={"path": str(_TOKEN_USAGE_LOG), "error": str(exc)},
            )

    def stage_summary(self, stage: str) -> dict[str, Any]:
        """Return aggregated ``{input, output, cost}`` for a stage."""
        totals = self._stage_totals.get(stage, {"input": 0, "output": 0})
        cost = _compute_cost(totals["input"], totals["output"])
        return {
            "input": totals["input"],
            "output": totals["output"],
            "cost": round(cost, 6),
        }

    def session_summary(self) -> dict[str, Any]:
        """Return aggregated ``{input, output, cost}`` for all stages."""
        total_in = sum(r.input_tokens for r in self._records)
        total_out = sum(r.output_tokens for r in self._records)
        cost = _compute_cost(total_in, total_out)
        return {
            "input": total_in,
            "output": total_out,
            "cost": round(cost, 6),
        }

    def recent_usage(self, window_seconds: int = 60) -> dict[str, int]:
        """Total tokens ``{input, output, total}`` in last *window_seconds* s."""
        cutoff = datetime.now(timezone.utc).timestamp() - window_seconds
        total_in = 0
        total_out = 0
        for rec in self._records:
            try:
                rec_ts = datetime.fromisoformat(rec.timestamp).timestamp()
            except (ValueError, TypeError):
                continue
            if rec_ts >= cutoff:
                total_in += rec.input_tokens
                total_out += rec.output_tokens
        return {"input": total_in, "output": total_out, "total": total_in + total_out}

    def total_records(self) -> int:
        """Return the number of recorded LLM calls."""
        return len(self._records)

    def flush_to_dict(self) -> dict[str, dict[str, int]]:
        """Per-stage totals as a plain dict (non-destructive)."""
        return {stage: dict(totals) for stage, totals in self._stage_totals.items()}

    def flush_to_records(self) -> list[dict[str, Any]]:
        """All usage records as plain dicts (non-destructive)."""
        return [asdict(r) for r in self._records]

    def reset(self) -> None:
        """Clear all accumulated token usage data."""
        self._records.clear()
        self._stage_totals.clear()
        self._stage_cost_warnings.clear()


_tracker: TokenTracker | None = None


def get_tracker() -> TokenTracker:
    """Return the module-level :class:`TokenTracker` singleton."""
    global _tracker
    if _tracker is None:
        _tracker = TokenTracker()
    return _tracker


def reset_tracker() -> None:
    """Reset the module-level tracker singleton (for test isolation)."""
    global _tracker
    _tracker = None


def format_stage_summary(stage: str, summary: dict[str, Any]) -> str:
    """Human-readable stage completion with token counts and cost."""
    in_k = round(summary.get("input", 0) / 1000, 1)
    out_k = round(summary.get("output", 0) / 1000, 1)
    cost = summary.get("cost", 0.0)
    cost_fmt = f"{cost:.6f}".rstrip("0").rstrip(".")
    return f"{stage} complete. Tokens: {in_k}K in, {out_k}K out. Cost: ${cost_fmt}"
