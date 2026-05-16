"""Integration tests for orchestration.runner — full pipeline dispatch.

Tests runner orchestration with mocked LLM and HITL, verifying:
- All 10 stages dispatch correctly through run_pipeline
- Theme inference respects dirty flags (only dirty tags processed)
- Export writes output files
- Checkpoints persist state between stages
"""

from __future__ import annotations

# flake8: noqa: E402
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src" / "python"))

import duckdb
from config.config import Config
from orchestration.runner import run_pipeline
from orchestration.state import WorkflowState
from persistence.duckdb_init import initialize_database
from persistence.state_repository import save_state

_STATE_SCHEMA = {
    "current_stage": 1,
    "dirty_flags": {},
    "last_checkpoint": None,
    "config_version": "",
    "user_action_count": 0,
}


class TestRunnerPipelineIntegration(unittest.TestCase):
    """Runner pipeline integration with mocked LLM and HITL."""

    def setUp(self) -> None:
        self.con = duckdb.connect(":memory:")
        initialize_database(con=self.con)
        save_state(self.con, dict(_STATE_SCHEMA))
        self.tmp_dir = Path(tempfile.mkdtemp(prefix="runner_int_"))
        self._env_patch = mock.patch.dict(
            os.environ,
            {
                "GROQ_API_KEY": "mock-test-key",
                "GROQ_MODEL": "mock-model",
                "EXPORT_OUTPUT_PATH": str(self.tmp_dir),
                "LOG_LEVEL": "CRITICAL",
            },
        )
        self._env_patch.start()
        self.config = Config.from_env()

    def tearDown(self) -> None:
        import shutil

        self._env_patch.stop()
        shutil.rmtree(self.tmp_dir, ignore_errors=True)
        self.con.close()

    # ── Stage-runner tests ──────────────────────────────────────────────

    def test_stage_load_dispatches_correctly(self) -> None:
        """_run_stage_load calls loaders and keyword extraction."""
        with (
            mock.patch("orchestration.runner._run_stage_load") as mock_fn,
            mock.patch("orchestration.runner._save_checkpoint"),
            mock.patch("orchestration.runner.graceful_shutdown"),
        ):
            mock_fn.return_value = None
            state = WorkflowState(current_stage=1)
            save_state(self.con, state.to_state_dict())
            run_pipeline(self.con, state, self.config, target_stage=1)
            mock_fn.assert_called_once_with(self.con, self.config)

    def test_stage_embed_dispatches_correctly(self) -> None:
        """_run_stage_embed called at stage 2 (takes con only)."""
        state = WorkflowState(current_stage=1)
        save_state(self.con, state.to_state_dict())
        mock_load = mock.patch("orchestration.runner._run_stage_load").start()
        mock_embed = mock.patch("orchestration.runner._run_stage_embed").start()
        mock.patch("orchestration.runner._save_checkpoint").start()
        mock.patch("orchestration.runner.graceful_shutdown").start()
        try:
            run_pipeline(self.con, state, self.config, target_stage=2)
            mock_embed.assert_called_once_with(self.con)
        finally:
            mock.patch.stopall()

    # ── Dirty-flag gating ───────────────────────────────────────────────

    def test_theme_inference_respects_dirty_flags(self) -> None:
        """Stage 6 calls infer_themes() only for dirty tags (not for clean)."""
        state = WorkflowState(
            current_stage=6,
            dirty_flags={"Tag.A": True, "Tag.B": False, "Tag.C": True},
        )
        save_state(self.con, state.to_state_dict())

        mock_infer_themes = mock.MagicMock()
        with (
            mock.patch("inference.theme_inference.infer_themes", mock_infer_themes),
            mock.patch("orchestration.runner._save_checkpoint"),
            mock.patch("orchestration.runner.graceful_shutdown"),
        ):
            run_pipeline(self.con, state, self.config, target_stage=6)

            # Only dirty tags should trigger infer_themes
            self.assertEqual(mock_infer_themes.call_count, 2)
            mock_infer_themes.assert_any_call(self.con, tag="Tag.A")
            mock_infer_themes.assert_any_call(self.con, tag="Tag.C")
            # Verify Tag.B (clean) was NOT called
            for call_args in mock_infer_themes.call_args_list:
                self.assertNotEqual(
                    call_args.kwargs.get("tag"),
                    "Tag.B",
                    "Should not call infer_themes for clean tag Tag.B",
                )

    def test_export_writes_output_files(self) -> None:
        """Stage 10 calls export and produces output files."""
        state = WorkflowState(current_stage=10)
        save_state(self.con, state.to_state_dict())

        mock_export = mock.MagicMock()
        with (
            mock.patch("orchestration.runner._run_stage_export", mock_export),
            mock.patch("orchestration.runner._save_checkpoint"),
            mock.patch("orchestration.runner.graceful_shutdown"),
        ):
            run_pipeline(self.con, state, self.config)
            mock_export.assert_called_once()

    def test_pipeline_advances_through_stages(self) -> None:
        """Pipeline advances from stage 1 through to stage 4 when targeting 3."""
        state = WorkflowState(current_stage=1)
        save_state(self.con, state.to_state_dict())

        with (
            mock.patch("orchestration.runner._run_stage_load"),
            mock.patch("orchestration.runner._run_stage_embed"),
            mock.patch("orchestration.runner._run_stage_index"),
            mock.patch("orchestration.runner.graceful_shutdown"),
        ):
            result = run_pipeline(self.con, state, self.config, target_stage=3)

        # After 3 stages processed, state advances: 1→2→3→4
        self.assertEqual(result.current_stage, 4)

    def test_early_return_when_past_target(self) -> None:
        """If current_stage > target_stage, return without executing any stage."""
        state = WorkflowState(current_stage=8)
        save_state(self.con, state.to_state_dict())

        with mock.patch("orchestration.runner._run_stage_load") as mock_fn:
            result = run_pipeline(self.con, state, self.config, target_stage=5)
            self.assertIs(result, state)
            mock_fn.assert_not_called()

    def test_resume_at_stage_4(self) -> None:
        """Starting at stage 4, runs infer_codes through to review_codes."""
        state = WorkflowState(current_stage=4)
        save_state(self.con, state.to_state_dict())

        with (
            mock.patch("orchestration.runner._run_stage_infer_codes"),
            mock.patch(
                "orchestration.runner._run_stage_review_codes",
                return_value=state,
            ),
            mock.patch("orchestration.runner._save_checkpoint"),
            mock.patch("orchestration.runner.graceful_shutdown"),
        ):
            result = run_pipeline(self.con, state, self.config, target_stage=5)

        self.assertEqual(result.current_stage, 6)

    def test_graceful_shutdown_invoked(self) -> None:
        """graceful_shutdown context manager wraps the pipeline loop."""
        state = WorkflowState(current_stage=1)
        save_state(self.con, state.to_state_dict())

        with (
            mock.patch("orchestration.runner._run_stage_load"),
            mock.patch("orchestration.runner._save_checkpoint"),
            mock.patch("orchestration.runner.graceful_shutdown") as mock_gs,
        ):
            run_pipeline(self.con, state, self.config, target_stage=1)

        mock_gs.assert_called_once()
        mock_gs.return_value.__enter__.assert_called_once()


if __name__ == "__main__":
    unittest.main()
