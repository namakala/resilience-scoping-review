"""Inference layer — Groq client, prompt templates, LLM orchestration."""

from .batching import (
    Batch,
    BatchableItem,
    group_by_tag,
    group_items_by_tag,
    split_batch_in_half,
)
from .code_inference import infer_codes
from .code_node_creation import create_code_nodes
from .exemplar_node_creation import ensure_exemplar_nodes
from .fewshot_loader import load_fewshot
from .groq_client import build_messages, complete, get_client, get_model
from .inference_status_crud import (
    batch_set_status,
    init_inference_status_table,
    set_status,
    set_status_draft,
)
from .inference_status_queries import (
    get_pending_items,
    get_stage_summary,
    get_status,
    reset_inference_status,
)
from .inference_status_types import (
    APPROVED,
    DRAFT,
    GENERATED,
    PENDING,
    REJECTED,
    STAGE_CODE,
    STAGE_INTERPRETATION,
    STAGE_THEME,
)
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
    "APPROVED",
    "Batch",
    "BatchableItem",
    "CodeInference",
    "DRAFT",
    "GENERATED",
    "InterpretationInference",
    "PENDING",
    "PromptBundle",
    "REJECTED",
    "STAGE_CODE",
    "STAGE_INTERPRETATION",
    "STAGE_THEME",
    "ThemeInference",
    "TokenLimitError",
    "TokenTracker",
    "UsageRecord",
    "batch_set_status",
    "build_messages",
    "call_complete_with_retry",
    "complete",
    "create_code_nodes",
    "ensure_exemplar_nodes",
    "format_stage_summary",
    "get_client",
    "get_model",
    "get_pending_items",
    "get_stage_summary",
    "get_status",
    "get_tracker",
    "group_by_tag",
    "group_items_by_tag",
    "infer_batch_with_retry",
    "infer_codes",
    "init_inference_status_table",
    "load_fewshot",
    "parse_code_response",
    "parse_interpretation_response",
    "parse_theme_response",
    "render_code_prompt",
    "render_interpretation_prompt",
    "render_theme_prompt",
    "reset_inference_status",
    "reset_tracker",
    "set_status",
    "set_status_draft",
    "split_batch_in_half",
    "track_tokens",
]
