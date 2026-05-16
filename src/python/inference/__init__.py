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
from .create_theme_nodes import create_theme_nodes
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
    ENTITY_INTERPRETATION,
    GENERATED,
    PENDING,
    REJECTED,
    STAGE_CODE,
    STAGE_INTERPRETATION,
    STAGE_THEME,
)
from .interpretation_creation import create_interpretation_nodes
from .interpretation_postprocess import (
    dedup_interpretation_names,
    flag_overlapping_themes,
    validate_theme_ids_exist,
)
from .interpretation_span_grouping import (
    build_ontology_subtree,
    build_tag_hierarchy,
    group_ready_tags_into_spans,
)
from .interpretation_synthesis import synthesize_interpretations
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
from .readiness import (
    check_tag_ready,
    get_ready_tags,
    is_tag_in_ready_list,
    remove_tag_from_ready,
)
from .retry import TokenLimitError, call_complete_with_retry, infer_batch_with_retry
from .seed_inference_status import seed_pending_exemplars
from .theme_inference import infer_themes
from .theme_loading_for_interpretation import load_approved_themes
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
    "build_ontology_subtree",
    "build_tag_hierarchy",
    "check_tag_ready",
    "CodeInference",
    "create_interpretation_nodes",
    "create_theme_nodes",
    "dedup_interpretation_names",
    "DRAFT",
    "ENTITY_INTERPRETATION",
    "flag_overlapping_themes",
    "GENERATED",
    "get_ready_tags",
    "group_ready_tags_into_spans",
    "InterpretationInference",
    "is_tag_in_ready_list",
    "load_approved_themes",
    "PENDING",
    "PromptBundle",
    "REJECTED",
    "remove_tag_from_ready",
    "STAGE_CODE",
    "STAGE_INTERPRETATION",
    "STAGE_THEME",
    "synthesize_interpretations",
    "ThemeInference",
    "TokenLimitError",
    "TokenTracker",
    "UsageRecord",
    "validate_theme_ids_exist",
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
    "infer_themes",
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
    "seed_pending_exemplars",
    "set_status",
    "set_status_draft",
    "split_batch_in_half",
    "track_tokens",
]
