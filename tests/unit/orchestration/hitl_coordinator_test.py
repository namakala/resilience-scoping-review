"""Tests for orchestration.hitl_coordinator — HITL coordination layer.

Tests cover:
- Delegation to correct review module per stage
- Auto-advance when no pending items exist
- Unknown stage handling
- State reload after HITL session
- Pending item counting in log output
"""

# flake8: noqa: E402
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(
    0,
    str(Path(__file__).parent.parent.parent.parent / "src" / "python"),
)  # noqa: E402

from orchestration.hitl_coordinator import _resolve_artifact_type, coordinate_hitl
from orchestration.state import WorkflowState


class TestResolveArtifactType(unittest.TestCase):
    """Stage-to-artifact-type mapping."""

    def test_stage_5_returns_code(self) -> None:
        self.assertEqual(_resolve_artifact_type(5), "code")

    def test_stage_7_returns_theme(self) -> None:
        self.assertEqual(_resolve_artifact_type(7), "theme")

    def test_stage_9_returns_interpretation(self) -> None:
        self.assertEqual(_resolve_artifact_type(9), "interpretation")

    def test_non_review_stage_returns_none(self) -> None:
        self.assertIsNone(_resolve_artifact_type(3))
        self.assertIsNone(_resolve_artifact_type(10))

    def test_out_of_range_returns_none(self) -> None:
        self.assertIsNone(_resolve_artifact_type(999))


class TestCoordinateHitl(unittest.TestCase):
    """Main coordination function behaviour."""

    def setUp(self) -> None:
        self.mock_con = mock.MagicMock()
        self.state = WorkflowState(current_stage=5, user_action_count=0)
        self.db_path = Path("/fake/db.duckdb")

    def test_delegates_to_code_review_when_pending_codes(self) -> None:
        """coordinate_hitl(5) invokes code review when codes are pending."""
        with (
            mock.patch(
                "orchestration.hitl_coordinator._query_pending",
                return_value=[{"id": 1}],
            ) as mock_query,
            mock.patch(
                "orchestration.hitl_coordinator._enter_review",
            ) as mock_enter,
            mock.patch(
                "persistence.state_repository.load_state",
                return_value=self.state.to_state_dict(),
            ),
        ):
            result = coordinate_hitl(self.mock_con, 5, self.state, self.db_path)

            mock_query.assert_called_once_with(self.mock_con, "code")
            mock_enter.assert_called_once_with(self.mock_con, "code", self.db_path)
            self.assertEqual(result.user_action_count, 0)

    def test_delegates_to_theme_review_when_pending_themes(self) -> None:
        """coordinate_hitl(7) invokes theme review when themes are pending."""
        with (
            mock.patch(
                "orchestration.hitl_coordinator._query_pending",
                return_value=[{"id": 1}],
            ) as mock_query,
            mock.patch(
                "orchestration.hitl_coordinator._enter_review",
            ) as mock_enter,
            mock.patch(
                "persistence.state_repository.load_state",
                return_value=self.state.to_state_dict(),
            ),
        ):
            result = coordinate_hitl(self.mock_con, 7, self.state, self.db_path)

            mock_query.assert_called_once_with(self.mock_con, "theme")
            mock_enter.assert_called_once_with(self.mock_con, "theme", self.db_path)
            self.assertIsInstance(result, WorkflowState)

    def test_delegates_to_interpretation_review_when_pending(self) -> None:
        """coordinate_hitl(9) invokes interpretation review when pending."""
        with (
            mock.patch(
                "orchestration.hitl_coordinator._query_pending",
                return_value=[{"id": 1}],
            ) as mock_query,
            mock.patch(
                "orchestration.hitl_coordinator._enter_review",
            ) as mock_enter,
            mock.patch(
                "persistence.state_repository.load_state",
                return_value=self.state.to_state_dict(),
            ),
        ):
            result = coordinate_hitl(self.mock_con, 9, self.state, self.db_path)

            mock_query.assert_called_once_with(self.mock_con, "interpretation")
            mock_enter.assert_called_once_with(
                self.mock_con, "interpretation", self.db_path
            )
            self.assertIsInstance(result, WorkflowState)

    def test_auto_advances_when_no_pending_items(self) -> None:
        """No pending items → skip HITL, return state unchanged."""
        with (
            mock.patch(
                "orchestration.hitl_coordinator._query_pending",
                return_value=[],
            ) as mock_query,
            mock.patch(
                "orchestration.hitl_coordinator._enter_review",
            ) as mock_enter,
        ):
            result = coordinate_hitl(self.mock_con, 5, self.state, self.db_path)

            mock_query.assert_called_once_with(self.mock_con, "code")
            mock_enter.assert_not_called()
            self.assertIs(result, self.state)  # same object, unchanged

    def test_unknown_stage_returns_state_unchanged(self) -> None:
        """Non-review stage → log warning, return state, no HITL calls."""
        state_before = WorkflowState(current_stage=3)
        with (
            mock.patch(
                "orchestration.hitl_coordinator._query_pending",
            ) as mock_query,
            mock.patch(
                "orchestration.hitl_coordinator._enter_review",
            ) as mock_enter,
        ):
            result = coordinate_hitl(self.mock_con, 3, state_before, self.db_path)

            mock_query.assert_not_called()
            mock_enter.assert_not_called()
            self.assertIs(result, state_before)

    def test_post_hitl_state_reload_captures_mutations(self) -> None:
        """State reloaded from DB after HITL reflects user_action_count changes."""
        updated_dict = self.state.to_state_dict()
        updated_dict["user_action_count"] = 5
        updated_dict["dirty_flags"] = {"Root": True}

        with (
            mock.patch(
                "orchestration.hitl_coordinator._query_pending",
                return_value=[{"id": 1}],
            ),
            mock.patch(
                "orchestration.hitl_coordinator._enter_review",
            ),
            mock.patch(
                "persistence.state_repository.load_state",
                return_value=updated_dict,
            ),
        ):
            result = coordinate_hitl(self.mock_con, 5, self.state, self.db_path)

            self.assertEqual(result.user_action_count, 5)
            self.assertEqual(result.dirty_flags, {"Root": True})

    def test_logs_pending_count(self) -> None:
        """Pending item count is logged for observability."""
        with (
            mock.patch(
                "orchestration.hitl_coordinator._query_pending",
                return_value=[{"id": 1}, {"id": 2}, {"id": 3}],
            ),
            mock.patch(
                "orchestration.hitl_coordinator._enter_review",
            ),
            mock.patch(
                "persistence.state_repository.load_state",
                return_value=self.state.to_state_dict(),
            ),
            mock.patch(
                "orchestration.hitl_coordinator.logger",
            ) as mock_logger,
        ):
            coordinate_hitl(self.mock_con, 5, self.state, self.db_path)

            mock_logger.info.assert_any_call(
                mock.ANY,  # "Stage %d — %d pending %s(s) to review"
                5,
                3,
                "code",
            )


if __name__ == "__main__":
    unittest.main()
