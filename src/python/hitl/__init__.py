"""HITL validation: interactive CLI for code, theme, and interpretation review."""

from .code_review import review_codes
from .code_review_actions import (
    handle_approve,
    handle_defer,
    handle_edit,
    handle_reject,
)
from .code_review_merge import handle_merge
from .edits import (
    invalidate_code_embedding,
    invalidate_interpretation_embedding,
    invalidate_theme_embedding,
)
from .interpretation_review import review_interpretations
from .interpretation_review_actions import (
    handle_approve_interpretation,
    handle_defer_interpretation,
    handle_edit_interpretation,
    handle_reject_interpretation,
)
from .interpretation_review_split import handle_split_interpretation
from .theme_review import review_themes
from .theme_review_actions import (
    handle_approve_theme,
    handle_defer_theme,
    handle_edit_theme,
    handle_reject_theme,
)
from .theme_review_merge import handle_merge_themes
from .user_action_log import log_user_action

__all__ = [
    "review_codes",
    "review_themes",
    "review_interpretations",
    "handle_approve",
    "handle_edit",
    "handle_merge",
    "handle_reject",
    "handle_defer",
    "handle_approve_theme",
    "handle_edit_theme",
    "handle_merge_themes",
    "handle_reject_theme",
    "handle_defer_theme",
    "handle_approve_interpretation",
    "handle_edit_interpretation",
    "handle_reject_interpretation",
    "handle_defer_interpretation",
    "handle_split_interpretation",
    "log_user_action",
    "invalidate_code_embedding",
    "invalidate_theme_embedding",
    "invalidate_interpretation_embedding",
]
