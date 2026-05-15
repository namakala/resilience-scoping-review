"""Workflow state machine for the thematic analysis pipeline."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional

from utils.exceptions import StateError

from .state_rules import MAX_STAGE, MIN_STAGE, STAGE_PREREQS, validate_state_fields


@dataclass(eq=True)
class WorkflowState:
    """Tracks pipeline progress, dirty flags, checkpoint metadata."""

    current_stage: int = 1
    dirty_flags: Dict[str, bool] = field(default_factory=dict)
    last_checkpoint: Optional[str] = None
    config_version: str = ""
    user_action_count: int = 0

    # ── Serialization ─────────────────────────────────────────────

    def to_json(self) -> str:
        """Serialize state to a JSON string."""
        return json.dumps(self.to_state_dict(), ensure_ascii=False)

    @classmethod
    def from_json(cls, json_str: str) -> WorkflowState:
        """Deserialize state from a JSON string."""
        try:
            data = json.loads(json_str)
        except json.JSONDecodeError as exc:
            raise StateError(f"Malformed state JSON: {exc}") from exc
        if not isinstance(data, dict):
            raise StateError(f"Expected JSON object, got " f"{type(data).__name__}")
        return cls.from_state_dict(data)

    def to_state_dict(self) -> Dict[str, Any]:
        """Convert to dict compatible with persistence layer."""
        return {
            "current_stage": self.current_stage,
            "dirty_flags": dict(self.dirty_flags),
            "last_checkpoint": self.last_checkpoint,
            "config_version": self.config_version,
            "user_action_count": self.user_action_count,
        }

    @classmethod
    def from_state_dict(cls, state_dict: Dict[str, Any]) -> WorkflowState:
        """Create from a dict (e.g. from load_state())."""
        return cls(
            current_stage=state_dict.get("current_stage", 1),
            dirty_flags=dict(state_dict.get("dirty_flags", {})),
            last_checkpoint=state_dict.get("last_checkpoint"),
            config_version=state_dict.get("config_version", ""),
            user_action_count=state_dict.get("user_action_count", 0),
        )

    # ── Stage transitions ─────────────────────────────────────────

    def _validate_stage(self, stage: int) -> None:
        """Check *stage* is in range and its prereqs are met."""
        if not (MIN_STAGE <= stage <= MAX_STAGE):
            raise StateError(
                f"Stage must be between {MIN_STAGE} and " f"{MAX_STAGE}, got {stage}"
            )
        prereqs = STAGE_PREREQS.get(stage, [])
        if not all(p <= self.current_stage for p in prereqs):
            raise StateError(
                f"Cannot transition from stage "
                f"{self.current_stage} to {stage}: "
                f"prerequisites not satisfied"
            )

    def can_advance_to(self, stage: int) -> bool:
        """Check whether advancement to *stage* is allowed."""
        if not (MIN_STAGE <= stage <= MAX_STAGE):
            return False
        prereqs = STAGE_PREREQS.get(stage, [])
        return all(p <= self.current_stage for p in prereqs)

    def advance_stage(self) -> None:
        """Advance to the next sequential stage (+1)."""
        if self.current_stage >= MAX_STAGE:
            raise StateError(f"Cannot advance: already at final stage " f"{MAX_STAGE}")
        self._validate_stage(self.current_stage + 1)
        self.current_stage += 1

    def set_stage(self, stage: int) -> None:
        """Set to a specific stage after validating prerequisites."""
        self._validate_stage(stage)
        self.current_stage = stage

    # ── Dirty flags ───────────────────────────────────────────────

    def set_dirty(self, tag: str, dirty: bool = True) -> None:
        """Mark an ontology tag as dirty or clean."""
        if not isinstance(tag, str):
            raise StateError(f"Tag must be a string, got " f"{type(tag).__name__}")
        self.dirty_flags[tag] = dirty

    # ── Config hash ───────────────────────────────────────────────

    @staticmethod
    def compute_config_hash(
        *file_paths: Path,
    ) -> str:
        """SHA-256 hex digest of config file contents.

        Skips non-existent paths. Used to detect configuration
        changes across sessions.
        """
        h = hashlib.sha256()
        for path in file_paths:
            if path is not None and path.exists():
                h.update(path.read_bytes())
        return h.hexdigest()

    # ── Post-init validation ──────────────────────────────────────

    def __post_init__(self) -> None:
        validate_state_fields(
            self.current_stage,
            self.dirty_flags,
            self.last_checkpoint,
            self.config_version,
            self.user_action_count,
        )
