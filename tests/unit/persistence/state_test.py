"""Comprehensive unit tests for session state persistence.

Tests cover:
- Serialization/deserialization roundtrips for all supported types
- save_state / load_state lifecycle (write, restart, read)
- Validation: invalid stage, malformed dirty_flags, extra keys allowed
- Atomic dirty flag updates via load-modify-save
- increment_user_action_count atomic counter
- set_last_checkpoint timestamp updates
- reset_state full table wipe
- Resume scenario: load_state returns defaults when no row exists
"""

# flake8: noqa: E402
import copy
import json
import shutil
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

# Add src/python to sys.path for imports
sys.path.insert(
    0,
    str(Path(__file__).parent.parent.parent.parent / "src" / "python"),
)

import duckdb
from persistence.state_repository import (
    DEFAULT_STATE,
    load_state,
    reset_state,
    save_state,
    validate_state,
)
from persistence.state_updates import (
    get_dirty_flags,
    increment_user_action_count,
    set_config_version,
    set_current_stage,
    set_last_checkpoint,
    update_dirty_flag,
)
from utils.exceptions import StateError


def _make_con():
    """Create an in-memory DuckDB connection with the session_state table."""
    con = duckdb.connect(":memory:")
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS session_state (
            key VARCHAR PRIMARY KEY,
            value VARCHAR NOT NULL,
            type VARCHAR NOT NULL
        );
        """
    )
    return con


def _make_file_con(tmpdir):
    """Create a file-based DuckDB connection for cross-connection tests."""
    db_path = tmpdir / "test.duckdb"
    con = duckdb.connect(str(db_path))
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS session_state (
            key VARCHAR PRIMARY KEY,
            value VARCHAR NOT NULL,
            type VARCHAR NOT NULL
        );
        """
    )
    con.commit()
    return con, db_path


class TestSerializationHelpers(unittest.TestCase):
    """Tests for internal _serialize/_deserialize helpers."""

    def test_serialize_roundtrip_int(self):
        """Integer values survive serialization roundtrip."""
        from persistence.state_serialization import _deserialize, _serialize

        for val in [0, 1, -1, 42, 999999]:
            json_str, type_hint = _serialize(val)
            self.assertEqual(_deserialize(json_str, type_hint), val)
            self.assertEqual(type_hint, "int")

    def test_serialize_roundtrip_float(self):
        """Float values survive serialization roundtrip."""
        from persistence.state_serialization import _deserialize, _serialize

        for val in [0.0, 1.5, -3.14, 0.001]:
            json_str, type_hint = _serialize(val)
            result = _deserialize(json_str, type_hint)
            self.assertAlmostEqual(result, val)
            self.assertEqual(type_hint, "float")

    def test_serialize_roundtrip_str(self):
        """String values survive serialization roundtrip."""
        from persistence.state_serialization import _deserialize, _serialize

        for val in ["", "hello", "unicode: \u00e9"]:
            json_str, type_hint = _serialize(val)
            self.assertEqual(_deserialize(json_str, type_hint), val)
            self.assertEqual(type_hint, "str")

    def test_serialize_roundtrip_bool(self):
        """Boolean values survive serialization roundtrip."""
        from persistence.state_serialization import _deserialize, _serialize

        for val in [True, False]:
            json_str, type_hint = _serialize(val)
            self.assertEqual(_deserialize(json_str, type_hint), val)
            self.assertEqual(type_hint, "bool")

    def test_serialize_roundtrip_dict(self):
        """Dict values survive serialization roundtrip."""
        from persistence.state_serialization import _deserialize, _serialize

        val = {"key": "value", "nested": {"a": 1}}
        json_str, type_hint = _serialize(val)
        self.assertEqual(_deserialize(json_str, type_hint), val)
        self.assertEqual(type_hint, "dict")

    def test_serialize_roundtrip_list(self):
        """List values survive serialization roundtrip."""
        from persistence.state_serialization import _deserialize, _serialize

        val = [1, "two", True, None]
        json_str, type_hint = _serialize(val)
        self.assertEqual(_deserialize(json_str, type_hint), val)
        self.assertEqual(type_hint, "list")

    def test_serialize_roundtrip_none(self):
        """None values serialize to 'null' type."""
        from persistence.state_serialization import _deserialize, _serialize

        json_str, type_hint = _serialize(None)
        self.assertEqual(json_str, "null")
        self.assertEqual(type_hint, "null")
        self.assertIsNone(_deserialize(json_str, type_hint))

    def test_serialize_unsupported_type_raises(self):
        """Unsupported types raise StateError."""
        from persistence.state_serialization import _serialize

        with self.assertRaises(StateError):
            _serialize(set([1, 2, 3]))

        with self.assertRaises(StateError):
            _serialize(b"bytes")


class TestLoadState(unittest.TestCase):
    """Tests for load_state function."""

    def test_load_state_returns_defaults_when_empty(self):
        """load_state returns DEFAULT_STATE when no workflow row exists."""
        con = _make_con()
        try:
            state = load_state(con)
            self.assertEqual(state["current_stage"], 1)
            self.assertEqual(state["dirty_flags"], {})
            self.assertIsNone(state["last_checkpoint"])
            self.assertEqual(state["config_version"], "")
            self.assertEqual(state["user_action_count"], 0)
            # Verify it is a deep copy (mutation doesn't affect DEFAULT_STATE)
            state["dirty_flags"]["test"] = True
            self.assertNotIn("test", DEFAULT_STATE["dirty_flags"])
        finally:
            con.close()

    def test_load_state_roundtrip(self):
        """save_state then load_state returns identical state (excluding last_checkpoint refresh)."""
        con = _make_con()
        try:
            initial = {
                "current_stage": 5,
                "dirty_flags": {"Tag.A": True, "Tag.B": False},
                "last_checkpoint": "2026-01-01T00:00:00",
                "config_version": "abc123",
                "user_action_count": 42,
            }
            save_state(con, initial)
            loaded = load_state(con)
            self.assertEqual(loaded["current_stage"], 5)
            self.assertEqual(loaded["dirty_flags"], {"Tag.A": True, "Tag.B": False})
            self.assertEqual(loaded["config_version"], "abc123")
            self.assertEqual(loaded["user_action_count"], 42)
            # last_checkpoint is refreshed by save_state, so skip exact match
            self.assertIsNotNone(loaded["last_checkpoint"])
        finally:
            con.close()

    def test_load_state_survives_restart(self):
        """State persists across connection close/reopen (simulates process restart)."""
        tmpdir = Path(tempfile.mkdtemp())
        try:
            con1, db_path = _make_file_con(tmpdir)
            try:
                state = {
                    "current_stage": 7,
                    "dirty_flags": {"X": True},
                    "last_checkpoint": "2026-05-01T12:00:00",
                    "config_version": "v1",
                    "user_action_count": 10,
                }
                save_state(con1, state)
            finally:
                con1.close()

            # Load state with new connection (simulates restart)
            con2 = _make_file_con(tmpdir)[0]
            try:
                loaded = load_state(con2)
                self.assertEqual(loaded["current_stage"], 7)
                self.assertEqual(loaded["dirty_flags"], {"X": True})
                self.assertEqual(loaded["config_version"], "v1")
                self.assertEqual(loaded["user_action_count"], 10)
            finally:
                con2.close()
        finally:
            shutil.rmtree(tmpdir)

    def test_load_state_fills_missing_keys(self):
        """load_state fills in defaults for any missing required keys."""
        con = _make_con()
        try:
            partial = {"current_stage": 3}
            save_state(con, partial)
            loaded = load_state(con)
            self.assertEqual(loaded["current_stage"], 3)
            self.assertEqual(loaded["dirty_flags"], {})
            self.assertEqual(loaded["config_version"], "")
            self.assertEqual(loaded["user_action_count"], 0)
        finally:
            con.close()

    def test_load_state_with_extra_keys(self):
        """Extra keys beyond the five required are preserved."""
        con = _make_con()
        try:
            state = copy.deepcopy(DEFAULT_STATE)
            state["current_stage"] = 2
            state["interpretation_ready_tags"] = ["Tag1", "Tag2"]
            state["token_usage"] = {"in": 5000, "out": 2000}
            save_state(con, state)
            loaded = load_state(con)
            self.assertEqual(loaded["interpretation_ready_tags"], ["Tag1", "Tag2"])
            self.assertEqual(loaded["token_usage"], {"in": 5000, "out": 2000})
        finally:
            con.close()


class TestSaveStateValidation(unittest.TestCase):
    """Tests for save_state validation."""

    def test_save_state_rejects_stage_below_1(self):
        """Stage < 1 raises StateError."""
        con = _make_con()
        try:
            state = copy.deepcopy(DEFAULT_STATE)
            state["current_stage"] = 0
            with self.assertRaises(StateError):
                save_state(con, state)
        finally:
            con.close()

    def test_save_state_rejects_stage_above_10(self):
        """Stage > 10 raises StateError."""
        con = _make_con()
        try:
            state = copy.deepcopy(DEFAULT_STATE)
            state["current_stage"] = 11
            with self.assertRaises(StateError):
                save_state(con, state)
        finally:
            con.close()

    def test_save_state_rejects_non_int_stage(self):
        """Non-integer stage raises StateError."""
        con = _make_con()
        try:
            state = copy.deepcopy(DEFAULT_STATE)
            state["current_stage"] = "three"
            with self.assertRaises(StateError):
                save_state(con, state)
        finally:
            con.close()

    def test_save_state_rejects_bool_stage(self):
        """Boolean stage (True/False) raises StateError."""
        con = _make_con()
        try:
            state = copy.deepcopy(DEFAULT_STATE)
            state["current_stage"] = True
            with self.assertRaises(StateError):
                save_state(con, state)
        finally:
            con.close()

    def test_save_state_rejects_non_dict_dirty_flags(self):
        """Non-dict dirty_flags raises StateError."""
        con = _make_con()
        try:
            state = copy.deepcopy(DEFAULT_STATE)
            state["dirty_flags"] = "not a dict"
            with self.assertRaises(StateError):
                save_state(con, state)
        finally:
            con.close()

    def test_save_state_rejects_non_bool_dirty_flag_value(self):
        """Non-bool value in dirty_flags raises StateError."""
        con = _make_con()
        try:
            state = copy.deepcopy(DEFAULT_STATE)
            state["dirty_flags"] = {"Tag.X": "yes"}
            with self.assertRaises(StateError):
                save_state(con, state)
        finally:
            con.close()

    def test_save_state_rejects_non_string_config_version(self):
        """Non-string config_version raises StateError."""
        con = _make_con()
        try:
            state = copy.deepcopy(DEFAULT_STATE)
            state["config_version"] = 123
            with self.assertRaises(StateError):
                save_state(con, state)
        finally:
            con.close()

    def test_save_state_rejects_negative_user_action_count(self):
        """Negative user_action_count raises StateError."""
        con = _make_con()
        try:
            state = copy.deepcopy(DEFAULT_STATE)
            state["user_action_count"] = -1
            with self.assertRaises(StateError):
                save_state(con, state)
        finally:
            con.close()

    def test_save_state_rejects_non_int_user_action_count(self):
        """Non-integer user_action_count raises StateError."""
        con = _make_con()
        try:
            state = copy.deepcopy(DEFAULT_STATE)
            state["user_action_count"] = "five"
            with self.assertRaises(StateError):
                save_state(con, state)
        finally:
            con.close()


class TestValidateState(unittest.TestCase):
    """Tests for validate_state function (standalone)."""

    def test_validate_valid_state_passes(self):
        """Valid state dict passes validation without raising."""
        state = {
            "current_stage": 5,
            "dirty_flags": {"Tag.A": True, "Tag.B": False},
            "last_checkpoint": "2026-01-01T00:00:00",
            "config_version": "v1",
            "user_action_count": 10,
        }
        # Should not raise
        validate_state(state)

    def test_validate_extra_keys_allowed(self):
        """Extra keys beyond required five are allowed."""
        state = copy.deepcopy(DEFAULT_STATE)
        state["current_stage"] = 3
        state["extra_field"] = "anything"
        state["another_extra"] = [1, 2, 3]
        # Should not raise
        validate_state(state)

    def test_validate_empty_dirty_flags_passes(self):
        """Empty dirty_flags dict is valid."""
        state = copy.deepcopy(DEFAULT_STATE)
        state["dirty_flags"] = {}
        validate_state(state)

    def test_validate_invalid_dirty_flags_key_type(self):
        """Non-string key in dirty_flags raises StateError."""
        state = copy.deepcopy(DEFAULT_STATE)
        state["dirty_flags"] = {123: True}
        with self.assertRaises(StateError):
            validate_state(state)


class TestAtomicDirtyFlagUpdates(unittest.TestCase):
    """Tests for atomic dirty flag updates via update_dirty_flag."""

    def test_update_dirty_flag_creates_row(self):
        """set_dirty creates the workflow row if it doesn't exist."""
        con = _make_con()
        try:
            # No workflow row yet
            update_dirty_flag(con, "NewTag", True)
            state = load_state(con)
            self.assertEqual(state["dirty_flags"], {"NewTag": True})
        finally:
            con.close()

    def test_update_dirty_flag_sets_true(self):
        """Setting dirty flag to True persists correctly."""
        con = _make_con()
        try:
            state = copy.deepcopy(DEFAULT_STATE)
            state["dirty_flags"] = {"Tag.A": False}
            save_state(con, state)
            update_dirty_flag(con, "Tag.A", True)
            flags = get_dirty_flags(con)
            self.assertTrue(flags.get("Tag.A"))
        finally:
            con.close()

    def test_update_dirty_flag_clears_to_false(self):
        """Setting dirty flag to False clears it."""
        con = _make_con()
        try:
            state = copy.deepcopy(DEFAULT_STATE)
            state["dirty_flags"] = {"Tag.A": True}
            save_state(con, state)
            update_dirty_flag(con, "Tag.A", False)
            flags = get_dirty_flags(con)
            self.assertFalse(flags.get("Tag.A"))
        finally:
            con.close()

    def test_update_dirty_flag_does_not_affect_other_fields(self):
        """Atomic dirty flag update preserves current_stage and other fields."""
        con = _make_con()
        try:
            state = {
                "current_stage": 7,
                "dirty_flags": {"Tag.A": False, "Tag.B": False},
                "last_checkpoint": "2026-01-01T00:00:00",
                "config_version": "v2",
                "user_action_count": 99,
            }
            save_state(con, state)
            update_dirty_flag(con, "Tag.B", True)
            loaded = load_state(con)
            self.assertEqual(loaded["current_stage"], 7)
            self.assertEqual(loaded["config_version"], "v2")
            self.assertEqual(loaded["user_action_count"], 99)
            self.assertTrue(loaded["dirty_flags"].get("Tag.B"))
            self.assertFalse(loaded["dirty_flags"].get("Tag.A"))
        finally:
            con.close()

    def test_update_dirty_flag_with_dot_in_tag_name(self):
        """Tags containing dots (e.g., 'Problem.Cause') are handled correctly."""
        con = _make_con()
        try:
            update_dirty_flag(con, "Problem.Cause", True)
            flags = get_dirty_flags(con)
            # The key should be the full tag name including the dot
            self.assertIn("Problem.Cause", flags)
            self.assertTrue(flags["Problem.Cause"])
        finally:
            con.close()

    def test_get_dirty_flags_empty_when_no_state(self):
        """get_dirty_flags returns empty dict when no workflow row exists."""
        con = _make_con()
        try:
            flags = get_dirty_flags(con)
            self.assertEqual(flags, {})
        finally:
            con.close()

    def test_multiple_dirty_flags_sequential_updates(self):
        """Multiple sequential dirty flag updates all persist."""
        con = _make_con()
        try:
            update_dirty_flag(con, "Tag1", True)
            update_dirty_flag(con, "Tag2", True)
            update_dirty_flag(con, "Tag1", False)
            flags = get_dirty_flags(con)
            self.assertFalse(flags.get("Tag1"))
            self.assertTrue(flags.get("Tag2"))
            self.assertNotIn("Tag3", flags)
        finally:
            con.close()

    def test_update_dirty_flag_invalid_tag_type(self):
        """Non-string tag raises StateError."""
        con = _make_con()
        try:
            with self.assertRaises(StateError):
                update_dirty_flag(con, 123, True)
        finally:
            con.close()


class TestIncrementUserActionCount(unittest.TestCase):
    """Tests for increment_user_action_count atomic counter."""

    def test_increment_from_zero(self):
        """Incrementing from zero (no row) works correctly."""
        con = _make_con()
        try:
            increment_user_action_count(con, 1)
            state = load_state(con)
            self.assertEqual(state["user_action_count"], 1)
        finally:
            con.close()

    def test_increment_multiple_times(self):
        """Multiple increments accumulate correctly."""
        con = _make_con()
        try:
            increment_user_action_count(con, 3)
            increment_user_action_count(con, 5)
            increment_user_action_count(con, 2)
            state = load_state(con)
            self.assertEqual(state["user_action_count"], 10)
        finally:
            con.close()

    def test_increment_with_custom_delta(self):
        """Custom delta value is applied correctly."""
        con = _make_con()
        try:
            increment_user_action_count(con, 7)
            state = load_state(con)
            self.assertEqual(state["user_action_count"], 7)
        finally:
            con.close()

    def test_increment_rejects_zero_delta(self):
        """Delta of 0 raises StateError."""
        con = _make_con()
        try:
            with self.assertRaises(StateError):
                increment_user_action_count(con, 0)
        finally:
            con.close()

    def test_increment_rejects_negative_delta(self):
        """Negative delta raises StateError."""
        con = _make_con()
        try:
            with self.assertRaises(StateError):
                increment_user_action_count(con, -1)
        finally:
            con.close()

    def test_increment_preserves_other_fields(self):
        """Increment doesn't affect other state fields."""
        con = _make_con()
        try:
            state = {
                "current_stage": 4,
                "dirty_flags": {"X": True},
                "config_version": "test",
                "user_action_count": 5,
            }
            save_state(con, state)
            increment_user_action_count(con, 3)
            loaded = load_state(con)
            self.assertEqual(loaded["current_stage"], 4)
            self.assertEqual(loaded["dirty_flags"], {"X": True})
            self.assertEqual(loaded["config_version"], "test")
            self.assertEqual(loaded["user_action_count"], 8)
        finally:
            con.close()


class TestSetCurrentStage(unittest.TestCase):
    """Tests for set_current_stage atomic setter."""

    def test_set_current_stage_valid(self):
        """Setting valid stage persists correctly."""
        con = _make_con()
        try:
            set_current_stage(con, 7)
            state = load_state(con)
            self.assertEqual(state["current_stage"], 7)
        finally:
            con.close()

    def test_set_current_stage_rejects_out_of_range(self):
        """Stage outside 1-10 raises StateError."""
        con = _make_con()
        try:
            with self.assertRaises(StateError):
                set_current_stage(con, 0)
            with self.assertRaises(StateError):
                set_current_stage(con, 11)
        finally:
            con.close()

    def test_set_current_stage_creates_row(self):
        """set_current_stage creates the workflow row if missing."""
        con = _make_con()
        try:
            set_current_stage(con, 3)
            state = load_state(con)
            self.assertEqual(state["current_stage"], 3)
        finally:
            con.close()


class TestSetConfigVersion(unittest.TestCase):
    """Tests for set_config_version."""

    def test_set_config_version(self):
        """Config version is set and persisted."""
        con = _make_con()
        try:
            set_config_version(con, "abc123def456")
            state = load_state(con)
            self.assertEqual(state["config_version"], "abc123def456")
        finally:
            con.close()

    def test_set_config_version_rejects_non_string(self):
        """Non-string config_version raises StateError."""
        con = _make_con()
        try:
            with self.assertRaises(StateError):
                set_config_version(con, 123)
        finally:
            con.close()


class TestSetLastCheckpoint(unittest.TestCase):
    """Tests for set_last_checkpoint."""

    def test_set_last_checkpoint_with_timestamp(self):
        """Explicit timestamp is stored correctly."""
        con = _make_con()
        try:
            ts = "2026-05-13T10:30:00.000000+00:00"
            set_last_checkpoint(con, ts)
            state = load_state(con)
            self.assertEqual(state["last_checkpoint"], ts)
        finally:
            con.close()

    def test_set_last_checkpoint_auto_now(self):
        """No timestamp argument sets to current UTC time."""
        con = _make_con()
        try:
            before = datetime.now(timezone.utc)
            set_last_checkpoint(con)
            after = datetime.now(timezone.utc)
            state = load_state(con)
            # Parse the stored timestamp and verify it's within the window
            stored = datetime.fromisoformat(state["last_checkpoint"])
            self.assertGreaterEqual(stored, before)
            self.assertLessEqual(stored, after)
        finally:
            con.close()


class TestResetState(unittest.TestCase):
    """Tests for reset_state full table wipe."""

    def test_reset_state_clears_all_rows(self):
        """reset_state deletes all rows from session_state."""
        con = _make_con()
        try:
            # Add workflow state
            save_state(con, copy.deepcopy(DEFAULT_STATE))
            # Verify row exists
            row = con.execute(
                "SELECT COUNT(*) FROM session_state WHERE key='workflow'"
            ).fetchone()
            self.assertEqual(row[0], 1)
            # Reset
            reset_state(con)
            # Verify all rows deleted
            count = con.execute("SELECT COUNT(*) FROM session_state").fetchone()[0]
            self.assertEqual(count, 0)
        finally:
            con.close()

    def test_reset_state_load_returns_defaults(self):
        """After reset, load_state returns default initial state."""
        con = _make_con()
        try:
            save_state(con, {"current_stage": 9, "user_action_count": 100})
            reset_state(con)
            state = load_state(con)
            self.assertEqual(state, DEFAULT_STATE)
        finally:
            con.close()


class TestResumeScenario(unittest.TestCase):
    """Tests simulating the --resume workflow from plan 64."""

    def test_resume_loads_from_checkpoint(self):
        """On resume, load_state returns the saved stage and dirty flags."""
        tmpdir = Path(tempfile.mkdtemp())
        try:
            con1, db_path = _make_file_con(tmpdir)
            try:
                # Simulate interrupted run at stage 4 with dirty flags
                state = {
                    "current_stage": 4,
                    "dirty_flags": {"Problem.Cause": True, "Problem.Impact": False},
                    "last_checkpoint": "2026-05-13T10:00:00",
                    "config_version": "hash123",
                    "user_action_count": 15,
                }
                save_state(con1, state)
            finally:
                con1.close()

            # Simulate --resume: reopen connection, load state
            con2 = _make_file_con(tmpdir)[0]
            try:
                loaded = load_state(con2)
                self.assertEqual(loaded["current_stage"], 4)
                self.assertTrue(loaded["dirty_flags"]["Problem.Cause"])
                self.assertFalse(loaded["dirty_flags"]["Problem.Impact"])
                self.assertEqual(loaded["config_version"], "hash123")
                self.assertEqual(loaded["user_action_count"], 15)
            finally:
                con2.close()
        finally:
            shutil.rmtree(tmpdir)

    def test_resume_fresh_start_no_state(self):
        """On first run (no state), load_state returns defaults."""
        con = _make_con()
        try:
            loaded = load_state(con)
            self.assertEqual(loaded["current_stage"], 1)
            self.assertEqual(loaded["dirty_flags"], {})
        finally:
            con.close()


if __name__ == "__main__":
    unittest.main()
