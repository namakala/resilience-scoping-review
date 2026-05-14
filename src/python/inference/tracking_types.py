"""Data types for token usage tracking.

Provides :class:`UsageRecord`, the dataclass used to represent a single
LLM call's token consumption, cost, and provenance.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone


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


__all__ = ["UsageRecord"]
