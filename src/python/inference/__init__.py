"""Inference layer — Groq client, prompt templates, LLM orchestration."""

from .batching import Batch, BatchableItem, group_by_tag, split_batch_in_half
from .fewshot_loader import load_fewshot
from .groq_client import build_messages, complete, get_client, get_model
from .parsing import (
    CodeInference,
    InterpretationInference,
    ThemeInference,
    parse_code_response,
    parse_interpretation_response,
    parse_theme_response,
)
from .prompts import (
    PromptBundle,
    render_code_prompt,
    render_interpretation_prompt,
    render_theme_prompt,
)
from .retry import TokenLimitError, call_complete_with_retry, infer_batch_with_retry
from .track_decorator import track_tokens
from .tracking import (
    TokenTracker,
    UsageRecord,
    format_stage_summary,
    get_tracker,
    reset_tracker,
)

__all__ = [
    "Batch",
    "BatchableItem",
    "CodeInference",
    "InterpretationInference",
    "PromptBundle",
    "ThemeInference",
    "TokenLimitError",
    "TokenTracker",
    "UsageRecord",
    "build_messages",
    "call_complete_with_retry",
    "complete",
    "format_stage_summary",
    "get_client",
    "get_model",
    "get_tracker",
    "group_by_tag",
    "infer_batch_with_retry",
    "load_fewshot",
    "parse_code_response",
    "parse_interpretation_response",
    "parse_theme_response",
    "render_code_prompt",
    "render_interpretation_prompt",
    "render_theme_prompt",
    "reset_tracker",
    "split_batch_in_half",
    "track_tokens",
]
