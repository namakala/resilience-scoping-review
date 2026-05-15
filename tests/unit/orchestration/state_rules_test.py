"""Unit tests for orchestration.state_rules — constants + validation."""

# flake8: noqa: E402
import sys
import unittest
from pathlib import Path

sys.path.insert(
    0,
    str(Path(__file__).parent.parent.parent.parent / "src" / "python"),
)  # noqa: E402

from orchestration.state_rules import (
    MAX_STAGE,
    MIN_STAGE,
    STAGE_PREREQS,
    validate_state_fields,
)
from utils.exceptions import StateError


class TestStageConstants(unittest.TestCase):
    """Sanity checks for stage constants."""

    def test_min_stage(self) -> None:
        self.assertEqual(MIN_STAGE, 1)

    def test_max_stage(self) -> None:
        self.assertEqual(MAX_STAGE, 10)

    def test_stage_prereqs_length(self) -> None:
        self.assertEqual(len(STAGE_PREREQS), 9)

    def test_stage_prereqs_order(self) -> None:
        for stage, prereqs in STAGE_PREREQS.items():
            self.assertListEqual(prereqs, [stage - 1])


class TestValidateStateFields(unittest.TestCase):
    """Tests for standalone validate_state_fields()."""

    VALID = {
        "current_stage": 5,
        "dirty_flags": {"A": True},
        "last_checkpoint": "2026-01-01",
        "config_version": "abc",
        "user_action_count": 10,
    }

    def test_valid_passes(self) -> None:
        validate_state_fields(**self.VALID)

    def test_valid_defaults_passes(self) -> None:
        validate_state_fields(
            current_stage=1,
            dirty_flags={},
            last_checkpoint=None,
            config_version="",
            user_action_count=0,
        )

    def test_invalid_stage_raises(self) -> None:
        with self.assertRaises(StateError):
            validate_state_fields(**{**self.VALID, "current_stage": 0})

    def test_invalid_dirty_flags_raises(self) -> None:
        with self.assertRaises(StateError):
            validate_state_fields(**{**self.VALID, "dirty_flags": "bad"})

    def test_invalid_last_checkpoint_raises(self) -> None:
        with self.assertRaises(StateError):
            validate_state_fields(**{**self.VALID, "last_checkpoint": 123})

    def test_invalid_config_version_raises(self) -> None:
        with self.assertRaises(StateError):
            validate_state_fields(**{**self.VALID, "config_version": 999})

    def test_invalid_user_action_count_raises(self) -> None:
        with self.assertRaises(StateError):
            validate_state_fields(
                **{
                    **self.VALID,
                    "user_action_count": -1,
                }
            )


if __name__ == "__main__":
    unittest.main()
