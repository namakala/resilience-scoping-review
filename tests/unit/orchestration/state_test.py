"""Unit tests for orchestration.state — WorkflowState class.

Tests cover:
- Default and custom initialisation
- JSON serialisation roundtrip
- Dict bridge for persistence integration
- Stage transitions (advance, set, can_advance_to)
- Dirty flag management
- Equality comparison
- Config hash computation
- Validation on construction
"""

# flake8: noqa: E402
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(
    0,
    str(Path(__file__).parent.parent.parent.parent / "src" / "python"),
)  # noqa: E402

from orchestration.state import MAX_STAGE, MIN_STAGE, WorkflowState
from utils.exceptions import StateError


class TestWorkflowStateInit(unittest.TestCase):
    """Tests for construction and default values."""

    def test_default_state(self) -> None:
        state = WorkflowState()
        self.assertEqual(state.current_stage, MIN_STAGE)
        self.assertEqual(state.dirty_flags, {})
        self.assertIsNone(state.last_checkpoint)
        self.assertEqual(state.config_version, "")
        self.assertEqual(state.user_action_count, 0)

    def test_custom_values(self) -> None:
        state = WorkflowState(
            current_stage=5,
            dirty_flags={"Tag.A": True},
            last_checkpoint="2026-01-01T00:00:00",
            config_version="abc123",
            user_action_count=42,
        )
        self.assertEqual(state.current_stage, 5)
        self.assertEqual(state.dirty_flags, {"Tag.A": True})
        self.assertEqual(state.last_checkpoint, "2026-01-01T00:00:00")
        self.assertEqual(state.config_version, "abc123")
        self.assertEqual(state.user_action_count, 42)

    def test_default_dirty_flags_is_fresh_dict(self) -> None:
        state1 = WorkflowState()
        state2 = WorkflowState()
        state1.dirty_flags["X"] = True
        self.assertNotIn("X", state2.dirty_flags)

    def test_invalid_stage_below_min(self) -> None:
        with self.assertRaises(StateError):
            WorkflowState(current_stage=0)

    def test_invalid_stage_above_max(self) -> None:
        with self.assertRaises(StateError):
            WorkflowState(current_stage=11)

    def test_invalid_stage_non_int(self) -> None:
        with self.assertRaises(StateError):
            WorkflowState(current_stage="three")  # type: ignore[arg-type]

    def test_invalid_stage_bool(self) -> None:
        with self.assertRaises(StateError):
            WorkflowState(current_stage=True)

    def test_invalid_dirty_flags_non_dict(self) -> None:
        with self.assertRaises(StateError):
            WorkflowState(dirty_flags="not-a-dict")  # type: ignore[arg-type]

    def test_invalid_dirty_flag_key_type(self) -> None:
        with self.assertRaises(StateError):
            WorkflowState(dirty_flags={123: True})  # type: ignore[dict-item]

    def test_invalid_dirty_flag_value_type(self) -> None:
        with self.assertRaises(StateError):
            WorkflowState(dirty_flags={"X": "yes"})  # type: ignore[dict-item]

    def test_invalid_last_checkpoint_type(self) -> None:
        with self.assertRaises(StateError):
            WorkflowState(last_checkpoint=123)  # type: ignore[arg-type]

    def test_invalid_config_version_type(self) -> None:
        with self.assertRaises(StateError):
            WorkflowState(config_version=123)  # type: ignore[arg-type]

    def test_invalid_user_action_count_negative(self) -> None:
        with self.assertRaises(StateError):
            WorkflowState(user_action_count=-1)

    def test_invalid_user_action_count_non_int(self) -> None:
        with self.assertRaises(StateError):
            WorkflowState(user_action_count="five")  # type: ignore[arg-type]

    def test_invalid_user_action_count_bool(self) -> None:
        with self.assertRaises(StateError):
            WorkflowState(user_action_count=True)


class TestWorkflowStateSerialization(unittest.TestCase):
    """Tests for JSON serialization (to_json / from_json)."""

    def test_to_json_roundtrip(self) -> None:
        original = WorkflowState(
            current_stage=7,
            dirty_flags={"Tag.A": True},
            last_checkpoint="2026-05-01T12:00:00",
            config_version="hash123",
            user_action_count=99,
        )
        json_str = original.to_json()
        restored = WorkflowState.from_json(json_str)
        self.assertEqual(original, restored)

    def test_to_json_default_state(self) -> None:
        state = WorkflowState()
        json_str = state.to_json()
        parsed = json.loads(json_str)
        self.assertEqual(parsed["current_stage"], 1)
        self.assertEqual(parsed["dirty_flags"], {})
        self.assertIsNone(parsed["last_checkpoint"])
        self.assertEqual(parsed["config_version"], "")
        self.assertEqual(parsed["user_action_count"], 0)

    def test_to_json_immutable(self) -> None:
        state = WorkflowState(dirty_flags={"A": True})
        json_str = state.to_json()
        state.dirty_flags["B"] = True
        parsed = json.loads(json_str)
        self.assertNotIn("B", parsed["dirty_flags"])

    def test_from_json_malformed(self) -> None:
        with self.assertRaises(StateError):
            WorkflowState.from_json("{invalid}")

    def test_from_json_non_dict(self) -> None:
        with self.assertRaises(StateError):
            WorkflowState.from_json("[1, 2, 3]")

    def test_from_json_partial_fills_defaults(self) -> None:
        json_str = json.dumps({"current_stage": 4})
        state = WorkflowState.from_json(json_str)
        self.assertEqual(state.current_stage, 4)
        self.assertEqual(state.dirty_flags, {})
        self.assertEqual(state.config_version, "")
        self.assertEqual(state.user_action_count, 0)

    def test_from_json_extra_keys_ignored(self) -> None:
        json_str = json.dumps(
            {
                "current_stage": 2,
                "dirty_flags": {},
                "last_checkpoint": None,
                "config_version": "",
                "user_action_count": 0,
                "unknown_key": "should_be_ignored",
            }
        )
        state = WorkflowState.from_json(json_str)
        self.assertEqual(state.current_stage, 2)


class TestWorkflowStateDictBridge(unittest.TestCase):
    """Tests for dict bridge (to_state_dict / from_state_dict)."""

    def test_to_state_dict_roundtrip(self) -> None:
        original = WorkflowState(
            current_stage=6,
            dirty_flags={"X": False},
            last_checkpoint="2026-01-01",
            config_version="v2",
            user_action_count=10,
        )
        d = original.to_state_dict()
        restored = WorkflowState.from_state_dict(d)
        self.assertEqual(original, restored)

    def test_from_state_dict_missing_keys(self) -> None:
        state = WorkflowState.from_state_dict({})
        self.assertEqual(state.current_stage, 1)
        self.assertEqual(state.dirty_flags, {})
        self.assertIsNone(state.last_checkpoint)
        self.assertEqual(state.config_version, "")
        self.assertEqual(state.user_action_count, 0)

    def test_from_state_dict_partial(self) -> None:
        state = WorkflowState.from_state_dict(
            {"current_stage": 9, "user_action_count": 5}
        )
        self.assertEqual(state.current_stage, 9)
        self.assertEqual(state.user_action_count, 5)
        self.assertEqual(state.dirty_flags, {})

    def test_from_state_dict_extra_keys_ignored(self) -> None:
        state = WorkflowState.from_state_dict(
            {
                "current_stage": 3,
                "dirty_flags": {},
                "last_checkpoint": None,
                "config_version": "",
                "user_action_count": 0,
                "extra_field": "ignored",
            }
        )
        self.assertEqual(state.current_stage, 3)

    def test_to_state_dict_includes_all_keys(self) -> None:
        state = WorkflowState()
        d = state.to_state_dict()
        self.assertIn("current_stage", d)
        self.assertIn("dirty_flags", d)
        self.assertIn("last_checkpoint", d)
        self.assertIn("config_version", d)
        self.assertIn("user_action_count", d)
        self.assertEqual(len(d), 5)


class TestWorkflowStateAdvanceStage(unittest.TestCase):
    """Tests for advance_stage method."""

    def test_advance_from_one(self) -> None:
        state = WorkflowState(current_stage=1)
        state.advance_stage()
        self.assertEqual(state.current_stage, 2)

    def test_advance_from_nine(self) -> None:
        state = WorkflowState(current_stage=9)
        state.advance_stage()
        self.assertEqual(state.current_stage, 10)

    def test_advance_from_max_raises(self) -> None:
        state = WorkflowState(current_stage=10)
        with self.assertRaises(StateError):
            state.advance_stage()

    def test_advance_sequential_progression(self) -> None:
        state = WorkflowState(current_stage=1)
        for expected in range(2, 11):
            state.advance_stage()
            self.assertEqual(
                state.current_stage,
                expected,
                f"Failed at stage {expected}",
            )

    def test_advance_cannot_skip(self) -> None:
        """advance_stage only goes +1, so skipping is impossible
        by design. This test verifies that calling advance twice
        goes 1 -> 2 -> 3, never skipping."""
        state = WorkflowState(current_stage=1)
        state.advance_stage()
        self.assertEqual(state.current_stage, 2)
        state.advance_stage()
        self.assertEqual(state.current_stage, 3)


class TestWorkflowStateSetStage(unittest.TestCase):
    """Tests for set_stage method."""

    def test_set_stage_valid(self) -> None:
        state = WorkflowState(current_stage=3)
        state.set_stage(4)
        self.assertEqual(state.current_stage, 4)

    def test_set_stage_same_stage(self) -> None:
        state = WorkflowState(current_stage=5)
        state.set_stage(5)
        self.assertEqual(state.current_stage, 5)

    def test_set_stage_skip_forward_raises(self) -> None:
        state = WorkflowState(current_stage=3)
        with self.assertRaises(StateError):
            state.set_stage(5)

    def test_set_stage_below_min_raises(self) -> None:
        state = WorkflowState(current_stage=1)
        with self.assertRaises(StateError):
            state.set_stage(0)

    def test_set_stage_above_max_raises(self) -> None:
        state = WorkflowState(current_stage=10)
        with self.assertRaises(StateError):
            state.set_stage(11)

    def test_set_stage_backward(self) -> None:
        """Going backward is allowed if target prereqs are met."""
        state = WorkflowState(current_stage=7)
        state.set_stage(3)
        self.assertEqual(state.current_stage, 3)


class TestWorkflowStateCanAdvanceTo(unittest.TestCase):
    """Tests for can_advance_to method."""

    def test_can_advance_to_next_stage(self) -> None:
        state = WorkflowState(current_stage=4)
        self.assertTrue(state.can_advance_to(5))

    def test_cannot_skip_stage(self) -> None:
        state = WorkflowState(current_stage=3)
        self.assertFalse(state.can_advance_to(5))

    def test_can_advance_to_current_stage(self) -> None:
        state = WorkflowState(current_stage=6)
        self.assertTrue(state.can_advance_to(6))

    def test_can_advance_to_below_min(self) -> None:
        state = WorkflowState(current_stage=1)
        self.assertFalse(state.can_advance_to(0))

    def test_can_advance_to_above_max(self) -> None:
        state = WorkflowState(current_stage=10)
        self.assertFalse(state.can_advance_to(11))

    def test_can_advance_to_max_when_ready(self) -> None:
        state = WorkflowState(current_stage=9)
        self.assertTrue(state.can_advance_to(10))

    def test_cannot_advance_to_max_early(self) -> None:
        state = WorkflowState(current_stage=8)
        self.assertFalse(state.can_advance_to(10))

    def test_can_advance_backward(self) -> None:
        """Backward check returns True (prereqs are met)."""
        state = WorkflowState(current_stage=8)
        self.assertTrue(state.can_advance_to(3))


class TestWorkflowStateDirtyFlags(unittest.TestCase):
    """Tests for set_dirty method."""

    def test_set_dirty_true(self) -> None:
        state = WorkflowState()
        state.set_dirty("Tag.A", True)
        self.assertTrue(state.dirty_flags["Tag.A"])

    def test_set_dirty_default(self) -> None:
        state = WorkflowState()
        state.set_dirty("Tag.A")
        self.assertTrue(state.dirty_flags["Tag.A"])

    def test_set_dirty_false(self) -> None:
        state = WorkflowState(dirty_flags={"Tag.A": True, "Tag.B": True})
        state.set_dirty("Tag.A", False)
        self.assertFalse(state.dirty_flags["Tag.A"])
        self.assertTrue(state.dirty_flags["Tag.B"])

    def test_set_dirty_overwrite(self) -> None:
        state = WorkflowState()
        state.set_dirty("Tag.X", True)
        state.set_dirty("Tag.X", False)
        self.assertFalse(state.dirty_flags["Tag.X"])

    def test_set_dirty_multiple_tags(self) -> None:
        state = WorkflowState()
        state.set_dirty("Tag.A", True)
        state.set_dirty("Tag.B", True)
        self.assertTrue(state.dirty_flags["Tag.A"])
        self.assertTrue(state.dirty_flags["Tag.B"])

    def test_set_dirty_dot_in_tag(self) -> None:
        state = WorkflowState()
        state.set_dirty("Problem.Cause", True)
        self.assertIn("Problem.Cause", state.dirty_flags)
        self.assertTrue(state.dirty_flags["Problem.Cause"])

    def test_set_dirty_non_string_tag_raises(self) -> None:
        state = WorkflowState()
        with self.assertRaises(StateError):
            state.set_dirty(123, True)  # type: ignore[arg-type]


class TestWorkflowStateEquality(unittest.TestCase):
    """Tests for __eq__."""

    def test_equal_states(self) -> None:
        state_a = WorkflowState(
            current_stage=5,
            dirty_flags={"A": True},
            last_checkpoint="2026-01-01",
            config_version="v1",
            user_action_count=10,
        )
        state_b = WorkflowState(
            current_stage=5,
            dirty_flags={"A": True},
            last_checkpoint="2026-01-01",
            config_version="v1",
            user_action_count=10,
        )
        self.assertEqual(state_a, state_b)

    def test_unequal_stage(self) -> None:
        a = WorkflowState(current_stage=3)
        b = WorkflowState(current_stage=4)
        self.assertNotEqual(a, b)

    def test_unequal_dirty_flags(self) -> None:
        a = WorkflowState(dirty_flags={"X": True})
        b = WorkflowState(dirty_flags={"X": False})
        self.assertNotEqual(a, b)

    def test_unequal_config_version(self) -> None:
        a = WorkflowState(config_version="abc")
        b = WorkflowState(config_version="def")
        self.assertNotEqual(a, b)

    def test_unequal_last_checkpoint(self) -> None:
        a = WorkflowState(last_checkpoint="2026-01-01")
        b = WorkflowState(last_checkpoint=None)
        self.assertNotEqual(a, b)

    def test_unequal_user_action_count(self) -> None:
        a = WorkflowState(user_action_count=0)
        b = WorkflowState(user_action_count=1)
        self.assertNotEqual(a, b)

    def test_defaults_are_equal(self) -> None:
        self.assertEqual(WorkflowState(), WorkflowState())

    def test_not_equal_to_non_workflow_state(self) -> None:
        state = WorkflowState()
        self.assertNotEqual(state, {"current_stage": 1})

    def test_not_equal_to_none(self) -> None:
        state = WorkflowState()
        self.assertNotEqual(state, None)


class TestWorkflowStateConfigHash(unittest.TestCase):
    """Tests for compute_config_hash static method."""

    def test_hash_is_deterministic(self) -> None:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".env", delete=False) as f:
            f.write("GROQ_API_KEY=test\n")
            f.flush()
            path = Path(f.name)
        try:
            h1 = WorkflowState.compute_config_hash(path)
            h2 = WorkflowState.compute_config_hash(path)
            self.assertEqual(h1, h2)
        finally:
            path.unlink()

    def test_hash_changes_when_content_changes(self) -> None:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".env", delete=False) as f:
            f.write("VERSION=1\n")
            f.flush()
            path = Path(f.name)
        try:
            h1 = WorkflowState.compute_config_hash(path)
            path.write_text("VERSION=2\n")
            h2 = WorkflowState.compute_config_hash(path)
            self.assertNotEqual(h1, h2)
        finally:
            path.unlink()

    def test_hash_non_existent_path(self) -> None:
        path = Path("/nonexistent/file.env")
        h = WorkflowState.compute_config_hash(path)
        self.assertEqual(len(h), 64)
        # Calling with only a nonexistent path produces a
        # deterministic "empty" hash (SHA-256 of empty input).
        empty_hash = WorkflowState.compute_config_hash()
        self.assertEqual(h, empty_hash)

    def test_hash_no_paths(self) -> None:
        h = WorkflowState.compute_config_hash()
        self.assertEqual(len(h), 64)
        self.assertIsInstance(h, str)

    def test_hash_none_path_skipped(self) -> None:
        """None in the path list is skipped without error."""
        h = WorkflowState.compute_config_hash(None)  # type: ignore[arg-type]
        self.assertEqual(len(h), 64)

    def test_hash_multiple_files(self) -> None:
        with (
            tempfile.NamedTemporaryFile(mode="w", suffix=".a", delete=False) as fa,
            tempfile.NamedTemporaryFile(mode="w", suffix=".b", delete=False) as fb,
        ):
            fa.write("content_a\n")
            fb.write("content_b\n")
            path_a = Path(fa.name)
            path_b = Path(fb.name)
        try:
            h = WorkflowState.compute_config_hash(path_a, path_b)
            self.assertEqual(len(h), 64)
            # Order matters: different order = different hash
            h_rev = WorkflowState.compute_config_hash(path_b, path_a)
            self.assertNotEqual(h, h_rev)
        finally:
            path_a.unlink()
            path_b.unlink()


class TestWorkflowStateStagePrereqs(unittest.TestCase):
    """Tests for stage prereq boundary conditions."""

    def test_min_stage_has_no_prereqs(self) -> None:
        state = WorkflowState(current_stage=MIN_STAGE)
        self.assertTrue(state.can_advance_to(MIN_STAGE + 1))
        state.advance_stage()
        self.assertEqual(state.current_stage, MIN_STAGE + 1)

    def test_max_stage_advance_raises(self) -> None:
        state = WorkflowState(current_stage=MAX_STAGE)
        with self.assertRaises(StateError):
            state.advance_stage()

    def test_sequential_advance_all_stages(self) -> None:
        """Iterate through every valid stage transition."""
        state = WorkflowState(current_stage=MIN_STAGE)
        for target in range(MIN_STAGE + 1, MAX_STAGE + 1):
            self.assertTrue(
                state.can_advance_to(target),
                f"Should advance {state.current_stage}->" f"{target}",
            )
            state.set_stage(target)
            self.assertEqual(state.current_stage, target)

    def test_every_skip_rejected(self) -> None:
        """Every two-stage skip from every position fails."""
        for current in range(MIN_STAGE, MAX_STAGE - 1):
            state = WorkflowState(current_stage=current)
            skip_to = current + 2
            self.assertFalse(
                state.can_advance_to(skip_to),
                f"Should reject skip {current}->{skip_to}",
            )
            with self.assertRaises(StateError):
                state.set_stage(skip_to)


if __name__ == "__main__":
    unittest.main()
