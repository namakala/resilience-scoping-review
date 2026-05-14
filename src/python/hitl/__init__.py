"""HITL validation: interactive CLI for code, theme, and interpretation review."""

from .code_review import review_codes
from .code_review_actions import (
    handle_approve,
    handle_defer,
    handle_edit,
    handle_reject,
)
from .code_review_merge import handle_merge
from .edits import invalidate_code_embedding, invalidate_theme_embedding
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
    "log_user_action",
    "invalidate_code_embedding",
    "invalidate_theme_embedding",
]
