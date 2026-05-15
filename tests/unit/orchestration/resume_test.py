"""Tests for orchestration.resume — session resume logic.

Covers:
- Fresh start (no --resume) returns stage 1 with config_version set
- Resume loads persisted state from DuckDB
- Config version match on resume proceeds normally
- Config mismatch raises SystemExit(2) without --force-resume
- Config mismatch with --force-resume proceeds with warning
- handle_reset clears session_state
- Config hash computation (with/without env file)
"""

# flake8: noqa: E402
import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(
    0,
    str(Path(__file__).parent.parent.parent.parent / "src" / "python"),
)  # noqa: E402

import duckdb
from orchestration.resume import _compute_config_hash, handle_reset, resolve_state

DEFAULT_STATE = {
    "current_stage": 1,
    "dirty_flags": {},
    "last_checkpoint": None,
    "config_version": "",
    "user_action_count": 0,
}


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


def _save_state(con, state):
    """Inject a persisted state dict into session_state."""
    payload = json.dumps(state)
    con.execute(
        "INSERT OR REPLACE INTO session_state (key, value, type) VALUES (?, ?, ?)",
        ["workflow", payload, "dict"],
    )


class TestResolveStateFreshStart(unittest.TestCase):
    """resolve_state with resume=False."""

    def setUp(self):
        self.con = _make_con()

    def tearDown(self):
        self.con.close()

    def test_fresh_start_returns_stage_1(self):
        state = resolve_state(self.con, resume=False)
        self.assertEqual(state.current_stage, 1)
        self.assertEqual(state.dirty_flags, {})

    def test_fresh_start_sets_config_version(self):
        state = resolve_state(self.con, resume=False)
        # Always a hash because CWD .env may exist; just verify length
        self.assertEqual(len(state.config_version), 64)

    def test_fresh_start_with_env_file_sets_hash(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".env", delete=False) as f:
            f.write("GROQ_API_KEY=test\n")
            env_path = Path(f.name)
        try:
            state = resolve_state(self.con, resume=False, env_file=env_path)
            self.assertEqual(len(state.config_version), 64)
        finally:
            env_path.unlink()

    def test_fresh_start_default_env_sets_hash(self):
        """If .env exists in CWD, hash is computed from it."""
        cwd_env = Path(".env")
        if cwd_env.exists():
            state = resolve_state(self.con, resume=False)
            self.assertEqual(len(state.config_version), 64)


class TestResolveStateResume(unittest.TestCase):
    """resolve_state with resume=True."""

    def setUp(self):
        self.con = _make_con()

    def tearDown(self):
        self.con.close()

    def test_resume_loads_persisted_state(self):
        persisted = copy.deepcopy(DEFAULT_STATE)
        persisted["current_stage"] = 6
        persisted["dirty_flags"] = {"Problem.Cause": True}
        persisted["last_checkpoint"] = "2026-05-13T10:00:00"
        persisted["config_version"] = "abc123"
        persisted["user_action_count"] = 42
        _save_state(self.con, persisted)

        # Mock config hash to match stored version so validation passes
        with mock.patch(
            "orchestration.resume._compute_config_hash", return_value="abc123"
        ):
            state = resolve_state(self.con, resume=True)
        self.assertEqual(state.current_stage, 6)
        self.assertEqual(state.dirty_flags, {"Problem.Cause": True})
        self.assertEqual(state.last_checkpoint, "2026-05-13T10:00:00")
        self.assertEqual(state.config_version, "abc123")
        self.assertEqual(state.user_action_count, 42)

    def test_resume_from_stage_4(self):
        """Resume after interrupted run at stage 4."""
        persisted = copy.deepcopy(DEFAULT_STATE)
        persisted["current_stage"] = 4
        persisted["last_checkpoint"] = "2026-05-13T08:00:00"
        _save_state(self.con, persisted)

        state = resolve_state(self.con, resume=True)
        self.assertEqual(state.current_stage, 4)
        self.assertEqual(state.last_checkpoint, "2026-05-13T08:00:00")

    def test_resume_no_state_uses_defaults(self):
        """No persistence row loads into defaults (stage 1)."""
        state = resolve_state(self.con, resume=True)
        self.assertEqual(state.current_stage, 1)

    def test_resume_restores_dirty_flags(self):
        """Dirty flags survive resume."""
        persisted = copy.deepcopy(DEFAULT_STATE)
        persisted["current_stage"] = 4
        persisted["dirty_flags"] = {"Root": True, "Problem.Cause": False}
        _save_state(self.con, persisted)

        state = resolve_state(self.con, resume=True)
        self.assertTrue(state.dirty_flags["Root"])
        self.assertFalse(state.dirty_flags["Problem.Cause"])

    def test_resume_logs_checkpoint(self):
        """Resume produces info log with stage and checkpoint."""
        persisted = copy.deepcopy(DEFAULT_STATE)
        persisted["current_stage"] = 5
        persisted["last_checkpoint"] = "2026-05-13T12:00:00"
        _save_state(self.con, persisted)

        with mock.patch("orchestration.resume.logger") as mock_logger:
            resolve_state(self.con, resume=True)
            mock_logger.info.assert_called_once_with(
                "Resuming from stage %d (checkpoint %s)",
                5,
                "2026-05-13T12:00:00",
            )

    def test_resume_no_checkpoint_logs_none(self):
        """Logs None checkpoint gracefully."""
        persisted = copy.deepcopy(DEFAULT_STATE)
        persisted["current_stage"] = 3
        _save_state(self.con, persisted)

        with mock.patch("orchestration.resume.logger") as mock_logger:
            resolve_state(self.con, resume=True)
            mock_logger.info.assert_called_once_with(
                "Resuming from stage %d (checkpoint %s)",
                3,
                None,
            )


class TestResumeConfigVersionValidation(unittest.TestCase):
    """Config version mismatch handling."""

    def setUp(self):
        self.con = _make_con()

    def tearDown(self):
        self.con.close()

    def _persist_with_hash(self, stored_hash):
        persisted = copy.deepcopy(DEFAULT_STATE)
        persisted["current_stage"] = 7
        persisted["config_version"] = stored_hash
        _save_state(self.con, persisted)

    def test_match_proceeds(self):
        """Stored version matches computed version."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".env", delete=False) as f:
            f.write("SETTING=value\n")
            env_path = Path(f.name)
        try:
            # Mock config hash to return the expected value
            from orchestration.state import WorkflowState

            expected = WorkflowState.compute_config_hash(env_path)
            self._persist_with_hash(expected)

            with mock.patch(
                "orchestration.resume._compute_config_hash",
                return_value=expected,
            ):
                state = resolve_state(self.con, resume=True, env_file=env_path)
            self.assertEqual(state.current_stage, 7)
        finally:
            env_path.unlink()

    def test_mismatch_raises_system_exit(self):
        """Stored version differs from computed → SystemExit(2)."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".env", delete=False) as f:
            f.write("MODEL=original\n")
            env_path = Path(f.name)
        try:
            self._persist_with_hash("old_hash_value")
            with self.assertRaises(SystemExit) as cm:
                resolve_state(self.con, resume=True, env_file=env_path)
            self.assertEqual(cm.exception.code, 2)
        finally:
            env_path.unlink()

    def test_mismatch_with_force_resume_proceeds(self):
        """Mismatch + force_resume=True proceeds without error."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".env", delete=False) as f:
            f.write("MODEL=v1\n")
            env_path = Path(f.name)
        try:
            self._persist_with_hash("different_hash")
            state = resolve_state(
                self.con,
                resume=True,
                force_resume=True,
                env_file=env_path,
            )
            self.assertEqual(state.current_stage, 7)
        finally:
            env_path.unlink()

    def test_mismatch_with_force_resume_logs_warning(self):
        """force_resume logs a warning about the mismatch."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".env", delete=False) as f:
            f.write("A=1\n")
            env_path = Path(f.name)
        try:
            self._persist_with_hash("old_hash")
            with mock.patch("orchestration.resume.logger") as mock_logger:
                resolve_state(
                    self.con,
                    resume=True,
                    force_resume=True,
                    env_file=env_path,
                )
                mock_logger.warning.assert_called_once()
                warning_msg = mock_logger.warning.call_args[0][0]
                self.assertIn("--force-resume", warning_msg)
        finally:
            env_path.unlink()

    def test_no_stored_version_skips_check(self):
        """Empty config_version in state skips validation."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".env", delete=False) as f:
            f.write("X=y\n")
            env_path = Path(f.name)
        try:
            persisted = copy.deepcopy(DEFAULT_STATE)
            persisted["current_stage"] = 3
            persisted["config_version"] = ""
            _save_state(self.con, persisted)

            # No mismatch error — stored version is ""
            state = resolve_state(self.con, resume=True, env_file=env_path)
            self.assertEqual(state.current_stage, 3)
        finally:
            env_path.unlink()


class TestHandleReset(unittest.TestCase):
    """handle_reset clears session_state."""

    def setUp(self):
        self.con = _make_con()

    def tearDown(self):
        self.con.close()

    def test_reset_clears_all_rows(self):
        persisted = copy.deepcopy(DEFAULT_STATE)
        persisted["current_stage"] = 9
        _save_state(self.con, persisted)

        handle_reset(self.con)

        count = self.con.execute("SELECT COUNT(*) FROM session_state").fetchone()[0]
        self.assertEqual(count, 0)

    def test_reset_after_empty_table(self):
        """Resetting an already-empty table does not error."""
        handle_reset(self.con)
        count = self.con.execute("SELECT COUNT(*) FROM session_state").fetchone()[0]
        self.assertEqual(count, 0)

    def test_reset_removes_workflow_row(self):
        _save_state(self.con, copy.deepcopy(DEFAULT_STATE))
        handle_reset(self.con)
        row = self.con.execute(
            "SELECT COUNT(*) FROM session_state WHERE key='workflow'"
        ).fetchone()
        self.assertEqual(row[0], 0)

    def test_reset_logs_action(self):
        with mock.patch("orchestration.resume.logger") as mock_logger:
            handle_reset(self.con)
            mock_logger.info.assert_called_once_with(
                "Session state reset — next run will start from stage 1."
            )


class TestComputeConfigHash(unittest.TestCase):
    """_compute_config_hash helper."""

    def test_no_env_files_returns_empty(self):
        """Without any .env files, returns empty string."""
        with mock.patch.object(Path, "exists", return_value=False):
            h = _compute_config_hash(None)
            self.assertEqual(h, "")

    def test_no_env_files_none_returns_empty(self):
        """None env_file and no CWD .env returns empty string."""
        with mock.patch.object(Path, "exists", return_value=False):
            h = _compute_config_hash(None)
        self.assertEqual(h, "")

    def test_with_env_file_returns_hash(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".env", delete=False) as f:
            f.write("KEY=value\n")
            env_path = Path(f.name)
        try:
            h = _compute_config_hash(env_path)
            self.assertEqual(len(h), 64)
            self.assertIsInstance(h, str)
        finally:
            env_path.unlink()

    def test_deterministic_hash(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".env", delete=False) as f:
            f.write("STATIC=1\n")
            env_path = Path(f.name)
        try:
            h1 = _compute_config_hash(env_path)
            h2 = _compute_config_hash(env_path)
            self.assertEqual(h1, h2)
        finally:
            env_path.unlink()

    def test_hash_changes_on_content_change(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".env", delete=False) as f:
            f.write("VERSION=1\n")
            env_path = Path(f.name)
        try:
            h1 = _compute_config_hash(env_path)
            env_path.write_text("VERSION=2\n")
            h2 = _compute_config_hash(env_path)
            self.assertNotEqual(h1, h2)
        finally:
            env_path.unlink()

    def test_skip_missing_env_file(self):
        """Non-existent env file and no CWD .env are skipped."""
        with mock.patch.object(Path, "exists", return_value=False):
            h = _compute_config_hash(Path("/nonexistent/.env"))
        self.assertEqual(h, "")

    def test_default_env_and_override_env(self):
        """Both .env and --env file contribute to hash."""
        cwd_env = Path(".env")
        if cwd_env.exists():
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".env", delete=False
            ) as f:
                f.write("EXTRA=value\n")
                extra_path = Path(f.name)
            try:
                h = _compute_config_hash(extra_path)
                self.assertEqual(len(h), 64)
            finally:
                extra_path.unlink()
        else:
            # No CWD .env — need to create one or skip
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".env", delete=False
            ) as f:
                f.write("DEFAULT=base\n")
                default_path = Path(f.name)
            try:
                h = _compute_config_hash(default_path)
                self.assertEqual(len(h), 64)
            finally:
                default_path.unlink()


class TestCLIIntegration(unittest.TestCase):
    """Spot-check that CLI flags are properly defined.

    Full CLI integration (e.g., invoking Click with --reset) is
    covered by cli_test.py — this just verifies the flags exist.
    """

    def test_resume_flag_in_help(self):
        from click.testing import CliRunner
        from orchestration.cli import cli

        runner = CliRunner()
        result = runner.invoke(cli, ["--help"])
        self.assertEqual(result.exit_code, 0)
        self.assertIn("--resume", result.output)
        self.assertIn("--force-resume", result.output)
        self.assertIn("--reset", result.output)


if __name__ == "__main__":
    unittest.main()
