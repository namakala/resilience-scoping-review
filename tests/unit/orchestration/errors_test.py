"""Tests for orchestration.errors — exit codes, integrity check, rebuild, fatal handler."""

# flake8: noqa: E402
import sys
from pathlib import Path
from unittest import mock

import duckdb

sys.path.insert(
    0, str(Path(__file__).parent.parent.parent.parent / "src" / "python")
)  # noqa: E402

from click.testing import CliRunner
from orchestration.cli import cli
from orchestration.errors import (
    _REBUILD_TABLES,
    EXIT_API_FAILURE,
    EXIT_CONFIG_ERROR,
    EXIT_STORAGE_CORRUPTION,
    EXIT_SUCCESS,
    EXIT_USER_INTERRUPT,
    check_integrity,
    handle_fatal_error,
    rebuild_database,
)
from utils.exceptions import ConfigurationError

# ── Exit code constants ─────────────────────────────────────────────


class TestExitCodes:
    """Exit code constants must match documented values."""

    def test_success_is_0(self) -> None:
        assert EXIT_SUCCESS == 0

    def test_user_interrupt_is_1(self) -> None:
        assert EXIT_USER_INTERRUPT == 1

    def test_config_error_is_2(self) -> None:
        assert EXIT_CONFIG_ERROR == 2

    def test_storage_corruption_is_3(self) -> None:
        assert EXIT_STORAGE_CORRUPTION == 3

    def test_api_failure_is_4(self) -> None:
        assert EXIT_API_FAILURE == 4


# ── check_integrity ─────────────────────────────────────────────────


class TestCheckIntegrity:
    """PRAGMA integrity_check wrapper."""

    def test_passes_when_ok(self) -> None:
        """Integrity passes when DuckDB returns 'ok'."""
        mock_con = mock.MagicMock(spec=duckdb.DuckDBPyConnection)
        mock_con.execute.return_value.fetchone.return_value = ("ok",)
        assert check_integrity(con=mock_con) is True

    def test_fails_when_not_ok(self) -> None:
        """Integrity fails when DuckDB returns an error message."""
        mock_con = mock.MagicMock(spec=duckdb.DuckDBPyConnection)
        mock_con.execute.return_value.fetchone.return_value = ("row with missing data",)
        assert check_integrity(con=mock_con) is False

    def test_fails_on_none_result(self) -> None:
        """Integrity fails when fetchone returns None."""
        mock_con = mock.MagicMock(spec=duckdb.DuckDBPyConnection)
        mock_con.execute.return_value.fetchone.return_value = None
        assert check_integrity(con=mock_con) is False

    def test_fails_on_duckdb_error(self) -> None:
        """Integrity fails when the query itself errors."""
        mock_con = mock.MagicMock(spec=duckdb.DuckDBPyConnection)
        mock_con.execute.side_effect = duckdb.Error("disk I/O error")
        assert check_integrity(con=mock_con) is False

    def test_fails_without_con_or_db_path(self) -> None:
        """Returns False when neither con nor db_path is given."""
        assert check_integrity() is False

    def test_opens_temp_connection_with_db_path(self) -> None:
        """Uses db_path to open a connection when con is None."""
        with (
            mock.patch(
                "orchestration.errors.get_connection",
                return_value=mock.MagicMock(spec=duckdb.DuckDBPyConnection),
            ) as mock_get_con,
        ):
            mock_con = mock_get_con.return_value
            mock_con.execute.return_value.fetchone.return_value = ("ok",)
            assert check_integrity(db_path="/tmp/test.duckdb") is True
            mock_get_con.assert_called_once_with("/tmp/test.duckdb")

    def test_closes_temp_connection(self) -> None:
        """Temporary connection is closed after the check."""
        with mock.patch(
            "orchestration.errors.get_connection",
            return_value=mock.MagicMock(spec=duckdb.DuckDBPyConnection),
        ) as mock_get_con:
            mock_con = mock_get_con.return_value
            mock_con.execute.return_value.fetchone.return_value = ("ok",)
            check_integrity(db_path="/tmp/test.duckdb")
            mock_con.close.assert_called_once()


# ── rebuild_database ────────────────────────────────────────────────


class TestRebuildDatabase:
    """Database rebuild — drop all tables, recreate schema."""

    def test_drops_all_tables(self) -> None:
        """Every table in _REBUILD_TABLES is dropped."""
        mock_con = mock.MagicMock(spec=duckdb.DuckDBPyConnection)
        with mock.patch("orchestration.errors.initialize_database"):
            rebuild_database(mock_con)
        for table in _REBUILD_TABLES:
            mock_con.execute.assert_any_call(f"DROP TABLE IF EXISTS {table}")

    def test_drops_sequences(self) -> None:
        """Sequences are also dropped."""
        mock_con = mock.MagicMock(spec=duckdb.DuckDBPyConnection)
        with mock.patch("orchestration.errors.initialize_database"):
            rebuild_database(mock_con)
        mock_con.execute.assert_any_call("DROP SEQUENCE IF EXISTS il_seq")
        mock_con.execute.assert_any_call("DROP SEQUENCE IF EXISTS ua_seq")
        mock_con.execute.assert_any_call("DROP SEQUENCE IF EXISTS nodes_id_seq")

    def test_reinitializes_schema(self) -> None:
        """initialize_database is called after dropping tables."""
        mock_con = mock.MagicMock(spec=duckdb.DuckDBPyConnection)
        with mock.patch("orchestration.errors.initialize_database") as mock_init:
            rebuild_database(mock_con)
            mock_init.assert_called_once_with(con=mock_con)

    def test_raises_on_drop_failure(self) -> None:
        """If a DROP fails, the exception propagates."""
        mock_con = mock.MagicMock(spec=duckdb.DuckDBPyConnection)
        mock_con.execute.side_effect = duckdb.Error("permission denied")
        with mock.patch("orchestration.errors.initialize_database"):
            import pytest

            with pytest.raises(duckdb.Error):
                rebuild_database(mock_con)


# ── handle_fatal_error ──────────────────────────────────────────────


class TestHandleFatalError:
    """Fatal error handler — logging and state save."""

    def test_returns_exit_code(self) -> None:
        """Returns the provided exit code."""
        result = handle_fatal_error(RuntimeError("boom"), exit_code=EXIT_API_FAILURE)
        assert result == EXIT_API_FAILURE

    def test_logs_error_type(self) -> None:
        """Logs the exception class name as error_type."""
        with mock.patch("orchestration.errors.logger") as mock_logger:
            handle_fatal_error(ValueError("bad value"), exit_code=EXIT_API_FAILURE)
            mock_logger.error.assert_called_once()
            _args, kwargs = mock_logger.error.call_args
            assert kwargs.get("extra", {}).get("error_type") == "ValueError"

    def test_saves_state_when_available(self) -> None:
        """Saves state dict when con and state are provided."""
        mock_con = mock.MagicMock(spec=duckdb.DuckDBPyConnection)
        state_dict = {"current_stage": 4}
        with mock.patch("persistence.state_repository.save_state") as mock_save:
            handle_fatal_error(
                RuntimeError("boom"),
                con=mock_con,
                state=state_dict,
            )
            mock_save.assert_called_once_with(mock_con, state_dict)

    def test_handles_state_object_with_to_state_dict(self) -> None:
        """Saves state via to_state_dict() when state is an object."""
        mock_con = mock.MagicMock(spec=duckdb.DuckDBPyConnection)
        mock_state = mock.MagicMock()
        mock_state.to_state_dict.return_value = {"current_stage": 7}
        with mock.patch("persistence.state_repository.save_state") as mock_save:
            handle_fatal_error(
                RuntimeError("boom"),
                con=mock_con,
                state=mock_state,
            )
            mock_save.assert_called_once_with(mock_con, {"current_stage": 7})

    def test_swallows_state_save_error(self) -> None:
        """Does not crash when state save fails."""
        mock_con = mock.MagicMock(spec=duckdb.DuckDBPyConnection)
        with mock.patch(
            "persistence.state_repository.save_state",
            side_effect=duckdb.Error("disk full"),
        ):
            result = handle_fatal_error(
                RuntimeError("boom"),
                con=mock_con,
                state={"current_stage": 4},
            )
            assert result == EXIT_API_FAILURE


# ── cli.main() integration ──────────────────────────────────────────


class TestCliMainErrorHandling:
    """Error handling in cli.main() must return correct exit codes."""

    def setup_method(self) -> None:
        self.runner = CliRunner()

    def test_keyboard_interrupt_returns_1(self) -> None:
        """KeyboardInterrupt during CLI returns exit code 1."""

        def _raise_interrupt(**kwargs):
            raise KeyboardInterrupt()

        with mock.patch("orchestration.cli.cli", side_effect=_raise_interrupt):
            from orchestration.cli import main

            assert main([]) == EXIT_USER_INTERRUPT

    def test_duckdb_error_returns_3(self) -> None:
        """duckdb.Error returns exit code 3."""

        def _raise_duckdb(**kwargs):
            raise duckdb.Error("disk I/O error")

        with (
            mock.patch("orchestration.cli.cli", side_effect=_raise_duckdb),
            mock.patch("orchestration.cli._try_rebuild", return_value=True),
        ):
            from orchestration.cli import main

            assert main([]) == EXIT_STORAGE_CORRUPTION

    def test_configuration_error_returns_2(self) -> None:
        """ConfigurationError returns exit code 2."""

        def _raise_config(**kwargs):
            raise ConfigurationError("missing GROQ_API_KEY")

        with mock.patch("orchestration.cli.cli", side_effect=_raise_config):
            from orchestration.cli import main

            assert main([]) == EXIT_CONFIG_ERROR

    def test_generic_exception_returns_4(self) -> None:
        """Any other exception returns exit code 4."""

        def _raise_generic(**kwargs):
            raise RuntimeError("unexpected")

        with mock.patch("orchestration.cli.cli", side_effect=_raise_generic):
            from orchestration.cli import main

            assert main([]) == EXIT_API_FAILURE

    def test_click_exception_returns_2(self) -> None:
        """click.ClickException returns exit code 2 (config error)."""
        import click

        def _raise_click(**kwargs):
            raise click.ClickException("bad arg")

        with mock.patch("orchestration.cli.cli", side_effect=_raise_click):
            from orchestration.cli import main

            assert main([]) == EXIT_CONFIG_ERROR

    def test_success_returns_0(self) -> None:
        """Successful execution returns exit code 0."""
        from orchestration.cli import main

        assert main(["--help"]) == EXIT_SUCCESS
