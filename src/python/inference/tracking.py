"""Token usage tracking middleware for Groq API calls.

Logs input/output tokens per call, accumulates per-session totals,
estimates costs, warns on excessive stage cost, and exposes a sliding
window of recent usage for rate-limit awareness (Feature 35).

Usage:
    from inference.tracking import (
        TokenTracker,
        get_tracker,
        reset_tracker,
        track_tokens,
        format_stage_summary,
    )

    tracker = get_tracker()

    # After each LLM call:
    tracker.record("code_inference", batch_id="tag_root_batch_00",
                   input_tokens=500, output_tokens=200)

    # At end of stage:
    summary = tracker.stage_summary("code_inference")
    print(format_stage_summary("code_inference", summary))

    # Query recent usage for rate-limit check:
    recent = tracker.recent_usage(window_seconds=60)

    # Persist to session_state:
    state["token_usage"] = tracker.flush_to_dict()
    state["token_records"] = tracker.flush_to_records()

    # Decorator form:
    @track_tokens("code_inference")
    def infer_batch(prompt, **kwargs):
        return complete(prompt)
"""

import functools
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

from config import (
    max_stage_cost_usd,
    token_cost_input_per_million,
    token_cost_output_per_million,
)
from utils.logging import get_logger

logger = get_logger(__name__)

_TOKEN_USAGE_LOG = Path("data/output/token_usage.log")


# ── Dataclasses ──────────────────────────────────────────────────────────────


@dataclass
class UsageRecord:
    """Token usage for a single LLM call.

    Attributes
    ----------
    stage : str
        Pipeline stage name (e.g. ``"code_inference"``).
    batch_id : str
        Batch identifier from the batching module.
    input_tokens : int
        Prompt token count (``usage.prompt_tokens``).
    output_tokens : int
        Completion token count (``usage.completion_tokens``).
    cost_usd : float
        Estimated cost in USD based on configured rates.
    timestamp : str
        ISO 8601 UTC timestamp of when the record was created.
    """

    stage: str
    batch_id: str
    input_tokens: int
    output_tokens: int
    cost_usd: float
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


# ── Cost helpers ─────────────────────────────────────────────────────────────


def _compute_cost(input_tokens: int, output_tokens: int) -> float:
    """Calculate estimated cost in USD for given token counts."""
    return (
        input_tokens / 1_000_000 * token_cost_input_per_million()
        + output_tokens / 1_000_000 * token_cost_output_per_million()
    )


# ── Token tracker ────────────────────────────────────────────────────────────


class TokenTracker:
    """In-memory accumulator for token usage across pipeline stages.

    Records individual :class:`UsageRecord` entries (with timestamps)
    and maintains per-stage aggregate totals. The record list supports
    sliding-window queries for rate-limit awareness (Feature 35).

    Thread-safety note: This class is **not** thread-safe. The pipeline
    is single-threaded (sequential batch processing), so this is not a
    concern in practice.
    """

    def __init__(self) -> None:
        self._records: list[UsageRecord] = []
        self._stage_totals: dict[str, dict[str, int]] = {}
        self._stage_cost_warnings: set[str] = set()

    # ── Recording ────────────────────────────────────────────────────────

    def record(
        self,
        stage: str,
        batch_id: str,
        input_tokens: int,
        output_tokens: int,
    ) -> UsageRecord:
        """Record token usage for one LLM call.

        Writes a structured JSON line to ``token_usage.log``, updates the
        in-memory accumulator, and logs a warning if the stage's total
        cost exceeds the configured threshold.

        Parameters
        ----------
        stage : str
            Pipeline stage name.
        batch_id : str
            Batch identifier (e.g. ``"tag_root_batch_00"``).
        input_tokens : int
            Prompt token count from the API response.
        output_tokens : int
            Completion token count from the API response.

        Returns
        -------
        UsageRecord
            The newly created usage record.
        """
        cost = _compute_cost(input_tokens, output_tokens)
        record = UsageRecord(
            stage=stage,
            batch_id=batch_id,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=round(cost, 6),
        )

        # Append to chronological record list
        self._records.append(record)

        # Update per-stage aggregates
        stage_acc = self._stage_totals.setdefault(stage, {"input": 0, "output": 0})
        stage_acc["input"] += input_tokens
        stage_acc["output"] += output_tokens

        # Write structured log entry
        self._write_log_entry(record)

        # Warn if stage cost exceeds threshold
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

        return record

    @staticmethod
    def _write_log_entry(record: UsageRecord) -> None:
        """Append a single JSON line to ``token_usage.log``."""
        try:
            _TOKEN_USAGE_LOG.parent.mkdir(parents=True, exist_ok=True)
            with open(_TOKEN_USAGE_LOG, "a") as f:
                f.write(json.dumps(asdict(record), ensure_ascii=False) + "\n")
        except OSError as exc:
            logger.error(
                "Failed to write token usage log",
                extra={"path": str(_TOKEN_USAGE_LOG), "error": str(exc)},
            )

    # ── Queries ──────────────────────────────────────────────────────────

    def stage_summary(self, stage: str) -> dict[str, Any]:
        """Return aggregated token and cost summary for a single stage.

        Returns a dict with keys ``input``, ``output``, ``cost``.
        Returns zeroed values if the stage has no recorded usage.
        """
        totals = self._stage_totals.get(stage, {"input": 0, "output": 0})
        cost = _compute_cost(totals["input"], totals["output"])
        return {
            "input": totals["input"],
            "output": totals["output"],
            "cost": round(cost, 6),
        }

    def session_summary(self) -> dict[str, Any]:
        """Return aggregated token and cost summary for the entire session.

        Returns a dict with keys ``input``, ``output``, ``cost``.
        """
        total_in = sum(r.input_tokens for r in self._records)
        total_out = sum(r.output_tokens for r in self._records)
        cost = _compute_cost(total_in, total_out)
        return {
            "input": total_in,
            "output": total_out,
            "cost": round(cost, 6),
        }

    def recent_usage(self, window_seconds: int = 60) -> dict[str, int]:
        """Return total tokens used in the last *window_seconds* seconds.

        Useful for rate-limit awareness (Groq 8000 TPM limit). Returns
        ``{"input": int, "output": int, "total": int}``.

        Parameters
        ----------
        window_seconds : int
            Width of the sliding window in seconds (default 60).
        """
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
        return {
            "input": total_in,
            "output": total_out,
            "total": total_in + total_out,
        }

    def total_records(self) -> int:
        """Return the number of recorded LLM calls."""
        return len(self._records)

    # ── Persistence ──────────────────────────────────────────────────────

    def flush_to_dict(self) -> dict[str, dict[str, int]]:
        """Return per-stage totals as a plain dict for session_state storage.

        Returns ``{"code_inference": {"input": 1234, "output": 567}, ...}``.
        This does **not** clear the accumulator; it's a snapshot.
        """
        return {stage: dict(totals) for stage, totals in self._stage_totals.items()}

    def flush_to_records(self) -> list[dict[str, Any]]:
        """Return all usage records as plain dicts for session_state storage.

        This does **not** clear the record list; it's a snapshot.
        """
        return [asdict(r) for r in self._records]

    # ── Reset ────────────────────────────────────────────────────────────

    def reset(self) -> None:
        """Clear all accumulated token usage data."""
        self._records.clear()
        self._stage_totals.clear()
        self._stage_cost_warnings.clear()


# ── Singleton management ─────────────────────────────────────────────────────

_tracker: Optional[TokenTracker] = None


def get_tracker() -> TokenTracker:
    """Return the module-level :class:`TokenTracker` singleton.

    Creates the instance on first call.
    """
    global _tracker
    if _tracker is None:
        _tracker = TokenTracker()
    return _tracker


def reset_tracker() -> None:
    """Reset the module-level tracker singleton and create a fresh one.

    Called between tests for isolation.
    """
    global _tracker
    _tracker = None


# ── Decorator ────────────────────────────────────────────────────────────────


def track_tokens(stage_name: str) -> Callable:
    """Decorator that automatically records token usage from an LLM call.

    The wrapped function **must** return an object with a ``.usage``
    attribute that has ``.prompt_tokens`` and ``.completion_tokens``
    (i.e. a Groq ``ChatCompletion`` object). The decorator extracts
    usage, records it, and passes the response through unchanged.

    Usage::

        from inference.tracking import track_tokens

        @track_tokens("code_inference")
        def infer_batch(prompt, batch_id="unknown"):
            return complete(prompt)

    Parameters
    ----------
    stage_name : str
        Pipeline stage name passed to :meth:`TokenTracker.record`.

    Returns
    -------
    Callable
        Decorated function.
    """

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            result = func(*args, **kwargs)
            usage = getattr(result, "usage", None)
            if usage is not None:
                tracker = get_tracker()
                batch_id = kwargs.get("batch_id", "unknown")
                tracker.record(
                    stage=stage_name,
                    batch_id=batch_id,
                    input_tokens=getattr(usage, "prompt_tokens", 0),
                    output_tokens=getattr(usage, "completion_tokens", 0),
                )
            else:
                logger.debug(
                    "track_tokens(%s): response has no .usage attribute, skipping",
                    stage_name,
                )
            return result

        return wrapper

    return decorator


# ── Summary formatting ───────────────────────────────────────────────────────


def format_stage_summary(stage: str, summary: dict[str, Any]) -> str:
    """Return a human-readable summary string for stage completion.

    The output follows the format specified in AC #2::

        Code inference complete. Tokens: 50K in, 20K out. Cost: $0.015

    Parameters
    ----------
    stage : str
        Stage name (e.g. ``"code_inference"``). Displayed verbatim.
    summary : dict
        Dict with keys ``input``, ``output``, ``cost`` from
        :meth:`TokenTracker.stage_summary`.

    Returns
    -------
    str
        Formatted summary string.
    """
    in_k = round(summary.get("input", 0) / 1000, 1)
    out_k = round(summary.get("output", 0) / 1000, 1)
    cost = summary.get("cost", 0.0)
    # Format cost: strip trailing zeros, use at least 2 decimal places
    cost_fmt = f"{cost:.6f}".rstrip("0").rstrip(".")
    return f"{stage} complete. Tokens: {in_k}K in, {out_k}K out. " f"Cost: ${cost_fmt}"


__all__ = [
    "TokenTracker",
    "UsageRecord",
    "format_stage_summary",
    "get_tracker",
    "reset_tracker",
    "track_tokens",
]
