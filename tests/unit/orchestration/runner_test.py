"""Tests for orchestration.runner — stage-transition driver."""

# flake8: noqa: E402
import sys
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(
    0, str(Path(__file__).parent.parent.parent.parent / "src" / "python")
)  # noqa: E402

from orchestration.runner import (
    MAX_STAGE,
    REVIEW_STAGES,
    STAGE_NAMES,
    TYPE_TO_TARGET_STAGE,
    execute_stage,
    resolve_target_stage,
    run_pipeline,
)
from orchestration.state import WorkflowState


class TestStageConstants(unittest.TestCase):
    """Stage name mappings and review stage classification."""

    def test_all_stages_have_names(self) -> None:
        """All 10 stages (1-10) have a name defined."""
        for stage in range(1, 11):
            self.assertIn(stage, STAGE_NAMES)
            self.assertIsInstance(STAGE_NAMES[stage], str)

    def test_only_five_seven_nine_are_review(self) -> None:
        """Only stages 5, 7, 9 are classified as review stages."""
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


class TestExecuteStage(unittest.TestCase):
    """DAG execution wrapper per stage."""

    def setUp(self) -> None:
        self.mock_driver = mock.MagicMock()
        self.mock_con = mock.MagicMock()
        self.mock_metrics = mock.MagicMock()
        self.state = WorkflowState(current_stage=4, dirty_flags={"Root": True})

    def test_passes_dirty_flags_for_inference_stages(self) -> None:
        """Inference stages (4, 6, 8) receive dirty_flags from state."""
        for stage in (4, 6, 8):
            self.state.current_stage = stage
            with mock.patch(
                "orchestration.runner.execute_dag", return_value=mock.MagicMock()
            ) as mock_exec:
                execute_stage(
                    self.mock_driver,
                    stage,
                    self.mock_con,
                    self.state,
                    self.mock_metrics,
                )
                _, kwargs = mock_exec.call_args
                self.assertIn("inputs", kwargs)
                inputs = kwargs["inputs"]
                if inputs:
                    self.assertIn("dirty_flags", inputs)
                    self.assertEqual(inputs["dirty_flags"], {"Root": True})

    def test_no_dirty_flags_for_non_inference_stages(self) -> None:
        """Non-inference stages pass inputs=None or empty."""
        for stage in (1, 2, 3, 5, 7, 9, 10):
            self.state.current_stage = stage
            self.state.dirty_flags = {"Root": True}
            with mock.patch(
                "orchestration.runner.execute_dag", return_value=mock.MagicMock()
            ) as mock_exec:
                execute_stage(
                    self.mock_driver,
                    stage,
                    self.mock_con,
                    self.state,
                    self.mock_metrics,
                )
                _, kwargs = mock_exec.call_args
                inputs = kwargs.get("inputs")
                if inputs:
                    self.assertNotIn("dirty_flags", inputs)

    def test_stage_passed_through(self) -> None:
        """Stage number is forwarded to execute_dag."""
        with mock.patch(
            "orchestration.runner.execute_dag", return_value=mock.MagicMock()
        ) as mock_exec:
            execute_stage(
                self.mock_driver, 4, self.mock_con, self.state, self.mock_metrics
            )
            _, kwargs = mock_exec.call_args
            self.assertEqual(kwargs["stage"], 4)


class TestRunPipeline(unittest.TestCase):
    """Main pipeline loop behavior."""

    def setUp(self) -> None:
        self.mock_con = mock.MagicMock()
        self.config = mock.MagicMock()
        self.mock_exec_result = mock.MagicMock()
        self.mock_exec_result.node_executions = []

    def test_returns_early_if_past_target(self) -> None:
        """If current_stage > target_stage, return immediately."""
        state = WorkflowState(current_stage=8)
        result = run_pipeline(self.mock_con, state, self.config, target_stage=5)
        self.assertIs(result, state)
        self.assertEqual(result.current_stage, 8)

    def test_runs_stages_sequentially(self) -> None:
        """Pipeline advances through stages 1 to 3 — ends at next stage (4)."""
        state = WorkflowState(current_stage=1)
        with (
            mock.patch(
                "orchestration.runner.execute_dag",
                return_value=self.mock_exec_result,
            ),
            mock.patch(
                "orchestration.runner.save_state",
            ),
            mock.patch(
                "orchestration.runner.create_pipeline",
            ),
            mock.patch(
                "orchestration.runner.NodeCacheAdapter",
            ),
        ):
            result = run_pipeline(self.mock_con, state, self.config, target_stage=3)
            # advance_stage() runs after each processed stage, so 1→2→3→4
            self.assertEqual(result.current_stage, 4)

    def test_resumes_from_stage_4(self) -> None:
        """Starting at stage 4, pipeline processes stages 4 through 5 — ends at 6."""
        state = WorkflowState(current_stage=4)
        with (
            mock.patch(
                "orchestration.runner.execute_dag",
                return_value=self.mock_exec_result,
            ),
            mock.patch(
                "orchestration.runner.save_state",
            ),
            mock.patch(
                "orchestration.runner.create_pipeline",
            ),
            mock.patch(
                "orchestration.runner.NodeCacheAdapter",
            ),
            mock.patch(
                "orchestration.runner._run_hitl_review",
            ),
        ):
            result = run_pipeline(self.mock_con, state, self.config, target_stage=5)
            # Stage 4 processed → advance to 5 → stage 5 processed → advance to 6
            self.assertEqual(result.current_stage, 6)

    def test_checkpoint_saved_after_each_stage(self) -> None:
        """save_state is called after every stage execution."""
        state = WorkflowState(current_stage=1)
        with (
            mock.patch(
                "orchestration.runner.execute_dag",
                return_value=self.mock_exec_result,
            ),
            mock.patch(
                "orchestration.runner.save_state",
            ) as mock_save,
            mock.patch(
                "orchestration.runner.create_pipeline",
            ),
            mock.patch(
                "orchestration.runner.NodeCacheAdapter",
            ),
        ):
            run_pipeline(self.mock_con, state, self.config, target_stage=3)
            self.assertEqual(mock_save.call_count, 3)

    def test_hitl_invoked_at_review_stage(self) -> None:
        """HITL review is entered at stage 5."""
        state = WorkflowState(current_stage=5)
        with (
            mock.patch(
                "orchestration.runner.execute_dag",
                return_value=self.mock_exec_result,
            ),
            mock.patch(
                "orchestration.runner.save_state",
            ),
            mock.patch(
                "orchestration.runner.create_pipeline",
            ),
            mock.patch(
                "orchestration.runner.NodeCacheAdapter",
            ),
            mock.patch(
                "orchestration.runner._run_hitl_review",
            ) as mock_hitl,
        ):
            run_pipeline(self.mock_con, state, self.config, target_stage=6)
            mock_hitl.assert_called_once_with(self.mock_con, 5)

    def test_advance_stops_at_max_stage(self) -> None:
        """Pipeline stops after stage 10 without error."""
        state = WorkflowState(current_stage=10)
        with (
            mock.patch(
                "orchestration.runner.execute_dag",
                return_value=self.mock_exec_result,
            ),
            mock.patch(
                "orchestration.runner.save_state",
            ),
            mock.patch(
                "orchestration.runner.create_pipeline",
            ),
            mock.patch(
                "orchestration.runner.NodeCacheAdapter",
            ),
        ):
            result = run_pipeline(self.mock_con, state, self.config)
            self.assertEqual(result.current_stage, 10)

    def test_graceful_shutdown_wraps_loop(self) -> None:
        """graceful_shutdown context manager wraps the main loop."""
        state = WorkflowState(current_stage=1)
        with (
            mock.patch(
                "orchestration.runner.execute_dag",
                return_value=self.mock_exec_result,
            ),
            mock.patch(
                "orchestration.runner.save_state",
            ),
            mock.patch(
                "orchestration.runner.create_pipeline",
            ),
            mock.patch(
                "orchestration.runner.NodeCacheAdapter",
            ),
            mock.patch(
                "orchestration.runner.graceful_shutdown",
            ) as mock_gs,
        ):
            run_pipeline(self.mock_con, state, self.config, target_stage=1)
            mock_gs.assert_called_once()
            # Verify it was used as context manager
            mock_gs.return_value.__enter__.assert_called_once()


if __name__ == "__main__":
    unittest.main()
