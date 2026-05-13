"""Inference layer — Groq client, prompt templates, LLM orchestration."""

from .batching import Batch, BatchableItem, group_by_tag
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

__all__ = [
    "Batch",
    "BatchableItem",
    "CodeInference",
    "InterpretationInference",
    "PromptBundle",
    "ThemeInference",
    "build_messages",
    "complete",
    "get_client",
    "get_model",
    "group_by_tag",
    "load_fewshot",
    "parse_code_response",
    "parse_interpretation_response",
    "parse_theme_response",
    "render_code_prompt",
    "render_interpretation_prompt",
    "render_theme_prompt",
]
