"""Tests for orchestration.runner — sequential pipeline loop."""

# flake8: noqa: E402
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "src" / "python"))

from orchestration.runner import (
    MAX_STAGE,
    REVIEW_STAGES,
    STAGE_NAMES,
    TYPE_TO_TARGET_STAGE,
    resolve_target_stage,
    run_pipeline,
)
from orchestration.state import WorkflowState


class TestStageConstants(unittest.TestCase):
    """Stage name mappings and review stage classification."""

    def test_all_stages_have_names(self) -> None:
        for stage in range(1, 11):
            self.assertIn(stage, STAGE_NAMES)
            self.assertIsInstance(STAGE_NAMES[stage], str)

    def test_only_five_seven_nine_are_review(self) -> None:
        for stage in range(1, 11):
            if stage in (5, 7, 9):
                self.assertIn(stage, REVIEW_STAGES)
            else:
                self.assertNotIn(stage, REVIEW_STAGES)

    def test_type_to_target_stage_mappings(self) -> None:
        self.assertEqual(TYPE_TO_TARGET_STAGE["code"], 5)
        self.assertEqual(TYPE_TO_TARGET_STAGE["theme"], 7)
        self.assertEqual(TYPE_TO_TARGET_STAGE["interpretation"], 9)


class TestResolveTargetStage(unittest.TestCase):
    """Target stage resolution from type tuples."""

    def test_empty_tuple_returns_max(self) -> None:
        self.assertEqual(resolve_target_stage(()), MAX_STAGE)

    def test_code_returns_5(self) -> None:
        self.assertEqual(resolve_target_stage(("code",)), 5)

    def test_theme_returns_7(self) -> None:
        self.assertEqual(resolve_target_stage(("theme",)), 7)

    def test_interpretation_returns_9(self) -> None:
        self.assertEqual(resolve_target_stage(("interpretation",)), 9)

    def test_multiple_types_returns_max(self) -> None:
        self.assertEqual(resolve_target_stage(("code", "theme")), 7)
        self.assertEqual(resolve_target_stage(("code", "theme", "interpretation")), 9)


class TestRunPipeline(unittest.TestCase):
    """Sequential pipeline loop behavior."""

    def setUp(self) -> None:
        self.mock_con = mock.MagicMock()
        self.config = mock.MagicMock()
        self.config.bm25_tokenizer_config = "lowercase,split_by_space"
        self.config.export_output_path = Path("/tmp/test_output")

    def test_returns_early_if_past_target(self) -> None:
        state = WorkflowState(current_stage=8)
        result = run_pipeline(self.mock_con, state, self.config, target_stage=5)
        self.assertIs(result, state)
        self.assertEqual(result.current_stage, 8)

    def test_runs_stages_sequentially(self) -> None:
        state = WorkflowState(current_stage=1)
        patches = [
            mock.patch("orchestration.runner.save_state"),
            mock.patch("orchestration.runner._run_stage_load"),
            mock.patch("orchestration.runner._run_stage_embed"),
            mock.patch("orchestration.runner._run_stage_index"),
        ]
        for p in patches:
            p.start()
        try:
            result = run_pipeline(self.mock_con, state, self.config, target_stage=3)
            self.assertEqual(result.current_stage, 4)
        finally:
            mock.patch.stopall()

    def test_resumes_from_stage_4(self) -> None:
        state = WorkflowState(current_stage=4)
        mock_save = mock.patch("orchestration.runner.save_state").start()
        mock.patch("orchestration.runner._run_stage_infer_codes").start()
        mock_review = mock.patch("orchestration.runner._run_stage_review_codes").start()
        mock_review.return_value = state
        try:
            result = run_pipeline(self.mock_con, state, self.config, target_stage=5)
            self.assertEqual(result.current_stage, 6)
        finally:
            mock.patch.stopall()

    def test_checkpoint_saved_after_each_stage(self) -> None:
        state = WorkflowState(current_stage=1)
        mock_save = mock.patch("orchestration.runner.save_state").start()
        mock.patch("orchestration.runner._run_stage_load").start()
        mock.patch("orchestration.runner._run_stage_embed").start()
        mock.patch("orchestration.runner._run_stage_index").start()
        try:
            run_pipeline(self.mock_con, state, self.config, target_stage=3)
            self.assertEqual(mock_save.call_count, 3)
        finally:
            mock.patch.stopall()

    def test_hitl_invoked_at_review_stage(self) -> None:
        state = WorkflowState(current_stage=5)
        mock_save = mock.patch("orchestration.runner.save_state").start()
        mock_review = mock.patch("orchestration.runner._run_stage_review_codes").start()
        mock_review.return_value = state
        try:
            result = run_pipeline(self.mock_con, state, self.config, target_stage=5)
            self.assertEqual(result.current_stage, 6)
            mock_review.assert_called_once()
        finally:
            mock.patch.stopall()

    def test_export_at_stage_10(self) -> None:
        state = WorkflowState(current_stage=10)
        mock_save = mock.patch("orchestration.runner.save_state").start()
        mock_export = mock.patch("orchestration.runner._run_stage_export").start()
        try:
            run_pipeline(self.mock_con, state, self.config)
            mock_export.assert_called_once()
        finally:
            mock.patch.stopall()

    def test_graceful_shutdown_wraps_loop(self) -> None:
        state = WorkflowState(current_stage=1)
        mock_save = mock.patch("orchestration.runner.save_state").start()
        mock.patch("orchestration.runner._run_stage_load").start()
        mock.patch("orchestration.runner._run_stage_embed").start()
        mock.patch("orchestration.runner._run_stage_index").start()
        mock_gs = mock.patch("orchestration.runner.graceful_shutdown").start()
        try:
            run_pipeline(self.mock_con, state, self.config, target_stage=1)
            mock_gs.assert_called_once()
            mock_gs.return_value.__enter__.assert_called_once()
        finally:
            mock.patch.stopall()


if __name__ == "__main__":
    unittest.main()
