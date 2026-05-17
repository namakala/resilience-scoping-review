"""Tests for orchestration.cli — click CLI argument parsing and dispatch."""

# flake8: noqa: E402
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(
    0, str(Path(__file__).parent.parent.parent.parent / "src" / "python")
)  # noqa: E402

from click.testing import CliRunner
from orchestration.cli import cli


class TestCliHelp(unittest.TestCase):
    """Tests for --help output."""

    def setUp(self) -> None:
        self.runner = CliRunner()

    def test_help_shows_global_options(self) -> None:
        result = self.runner.invoke(cli, ["--help"])
        self.assertEqual(result.exit_code, 0)
        self.assertIn("--data", result.output)
        self.assertIn("--tags", result.output)
        self.assertIn("--env", result.output)
        self.assertIn("--resume", result.output)

    def test_help_shows_subcommands(self) -> None:
        result = self.runner.invoke(cli, ["--help"])
        self.assertEqual(result.exit_code, 0)
        self.assertIn("ingest", result.output)
        self.assertIn("run", result.output)

    def test_ingest_help_shows_options(self) -> None:
        result = self.runner.invoke(cli, ["ingest", "--help"])
        self.assertEqual(result.exit_code, 0)
        self.assertIn("--data", result.output)
        self.assertIn("--tags", result.output)
        self.assertIn("--force", result.output)
        self.assertIn("--dry-run", result.output)

    def test_run_help_shows_options(self) -> None:
        result = self.runner.invoke(cli, ["run", "--help"])
        self.assertEqual(result.exit_code, 0)
        self.assertIn("--type", result.output)
        self.assertIn("--all", result.output)
        self.assertIn("code", result.output)
        self.assertIn("theme", result.output)
        self.assertIn("interpretation", result.output)
        self.assertIn("--dry-run", result.output)


class TestCliIngest(unittest.TestCase):
    """Tests for the ingest subcommand."""

    def setUp(self) -> None:
        self.runner = CliRunner()
        self.tmpdir = tempfile.TemporaryDirectory()
        self.tmp = Path(self.tmpdir.name)
        self.data_csv = self.tmp / "data.csv"
        self.tags_csv = self.tmp / "tags.csv"
        self.data_csv.write_text("id,content\n1,test")
        self.tags_csv.write_text("tag,description\nroot,root tag")

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

    def test_dry_run_ingest_with_cli_args(self) -> None:
        """--dry-run with --data/--tags on subcommand."""
        result = self.runner.invoke(
            cli,
            [
                "ingest",
                "--dry-run",
                "--data",
                str(self.data_csv),
                "--tags",
                str(self.tags_csv),
            ],
        )
        self.assertEqual(result.exit_code, 0)
        self.assertIn("Dry-run", result.output)

    def test_dry_run_ingest_with_env(self) -> None:
        """--dry-run validates paths from env vars and exits 0."""
        with mock.patch.dict(
            "os.environ",
            {
                "DATA_PATH": str(self.data_csv),
                "TAGS_PATH": str(self.tags_csv),
                "GROQ_API_KEY": "sk-test",
            },
        ):
            result = self.runner.invoke(cli, ["ingest", "--dry-run"])
            self.assertEqual(result.exit_code, 0)
            self.assertIn("Dry-run", result.output)

    def test_ingest_missing_groq_key(self) -> None:
        """Missing GROQ_API_KEY exits with error.

        We mock load_dotenv to prevent .env from re-adding the key
        during the group callback.
        """
        with mock.patch("orchestration.config.load_dotenv"):
            with mock.patch.dict(
                "os.environ",
                {
                    "DATA_PATH": str(self.data_csv),
                    "TAGS_PATH": str(self.tags_csv),
                },
                clear=True,
            ):
                result = self.runner.invoke(cli, ["ingest", "--dry-run"])
                self.assertNotEqual(result.exit_code, 0)

    def test_ingest_missing_paths(self) -> None:
        """Missing data paths exit with error."""
        result = self.runner.invoke(
            cli,
            [
                "ingest",
                "--data",
                "/nonexistent/data.csv",
                "--tags",
                str(self.tags_csv),
            ],
        )
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("not found", result.output)


class TestCliRun(unittest.TestCase):
    """Tests for the run subcommand."""

    def setUp(self) -> None:
        self.runner = CliRunner()
        self.tmpdir = tempfile.TemporaryDirectory()
        self.tmp = Path(self.tmpdir.name)
        self.data_csv = self.tmp / "data.csv"
        self.tags_csv = self.tmp / "tags.csv"
        self.data_csv.write_text("id,content\n1,test")
        self.tags_csv.write_text("tag,description\nroot,root tag")

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

    def test_run_no_type_is_valid(self) -> None:
        """run (no --type) is valid — defaults to --all."""
        with mock.patch("orchestration.config.load_dotenv"):
            with mock.patch.dict(
                "os.environ",
                {
                    "GROQ_API_KEY": "sk-test",
                    "PROCESSED_DATA_PATH": str(self.tmp),
                },
                clear=True,
            ):
                result = self.runner.invoke(
                    cli,
                    [
                        "--data",
                        str(self.data_csv),
                        "--tags",
                        str(self.tags_csv),
                        "run",
                        "--dry-run",
                    ],
                )
                self.assertEqual(result.exit_code, 0)
                self.assertIn("All stages", result.output)

    def test_run_all_flag(self) -> None:
        """run --all is valid."""
        with mock.patch("orchestration.config.load_dotenv"):
            with mock.patch.dict(
                "os.environ",
                {
                    "GROQ_API_KEY": "sk-test",
                    "PROCESSED_DATA_PATH": str(self.tmp),
                },
                clear=True,
            ):
                result = self.runner.invoke(
                    cli,
                    [
                        "--data",
                        str(self.data_csv),
                        "--tags",
                        str(self.tags_csv),
                        "run",
                        "--all",
                        "--dry-run",
                    ],
                )
                self.assertEqual(result.exit_code, 0)
                self.assertIn("All stages", result.output)

    def test_run_single_type(self) -> None:
        """run --type code works."""
        with mock.patch("orchestration.config.load_dotenv"):
            with mock.patch.dict(
                "os.environ",
                {
                    "GROQ_API_KEY": "sk-test",
                    "PROCESSED_DATA_PATH": str(self.tmp),
                },
                clear=True,
            ):
                result = self.runner.invoke(
                    cli,
                    [
                        "--data",
                        str(self.data_csv),
                        "--tags",
                        str(self.tags_csv),
                        "run",
                        "--type",
                        "code",
                        "--dry-run",
                    ],
                )
                self.assertEqual(result.exit_code, 0)
                self.assertIn("code", result.output)

    def test_run_multiple_types(self) -> None:
        """run accepts multiple --type values."""
        with mock.patch("orchestration.config.load_dotenv"):
            with mock.patch.dict(
                "os.environ",
                {
                    "GROQ_API_KEY": "sk-test",
                    "PROCESSED_DATA_PATH": str(self.tmp),
                },
                clear=True,
            ):
                result = self.runner.invoke(
                    cli,
                    [
                        "--data",
                        str(self.data_csv),
                        "--tags",
                        str(self.tags_csv),
                        "run",
                        "--type",
                        "code",
                        "--type",
                        "theme",
                        "--dry-run",
                    ],
                )
                self.assertEqual(result.exit_code, 0)
                self.assertIn("code", result.output)
                self.assertIn("theme", result.output)

    def test_run_invalid_type(self) -> None:
        """Invalid --type value is rejected."""
        result = self.runner.invoke(
            cli,
            [
                "--data",
                str(self.data_csv),
                "--tags",
                str(self.tags_csv),
                "run",
                "--type",
                "invalid",
                "--dry-run",
            ],
        )
        self.assertNotEqual(result.exit_code, 0)

    def test_run_type_and_all_mutually_exclusive(self) -> None:
        """--type and --all cannot be used together."""
        result = self.runner.invoke(
            cli,
            [
                "--data",
                str(self.data_csv),
                "--tags",
                str(self.tags_csv),
                "run",
                "--all",
                "--type",
                "code",
                "--dry-run",
            ],
        )
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("mutually exclusive", result.output)


class TestCliGlobalOptions(unittest.TestCase):
    """Tests for global option handling."""

    def setUp(self) -> None:
        self.runner = CliRunner()
        self.tmpdir = tempfile.TemporaryDirectory()
        self.tmp = Path(self.tmpdir.name)
        self.data_csv = self.tmp / "data.csv"
        self.tags_csv = self.tmp / "tags.csv"
        self.data_csv.write_text("id,content\n1,test")
        self.tags_csv.write_text("tag,description\nroot,root tag")

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

    def test_global_data_tags_respected(self) -> None:
        """Global --data and --tags are passed to subcommands."""
        with mock.patch("orchestration.config.load_dotenv"):
            with mock.patch.dict(
                "os.environ",
                {"GROQ_API_KEY": "sk-test"},
                clear=True,
            ):
                result = self.runner.invoke(
                    cli,
                    [
                        "--data",
                        str(self.data_csv),
                        "--tags",
                        str(self.tags_csv),
                        "run",
                        "--type",
                        "code",
                        "--dry-run",
                    ],
                )
                self.assertEqual(result.exit_code, 0)

    def test_verbose_flag(self) -> None:
        """--verbose is accepted on subcommands."""
        result = self.runner.invoke(
            cli,
            [
                "--data",
                str(self.data_csv),
                "--tags",
                str(self.tags_csv),
                "ingest",
                "--verbose",
                "--dry-run",
            ],
        )
        self.assertEqual(result.exit_code, 0)

    def test_quiet_flag(self) -> None:
        """--quiet is accepted on subcommands."""
        result = self.runner.invoke(
            cli,
            [
                "--data",
                str(self.data_csv),
                "--tags",
                str(self.tags_csv),
                "ingest",
                "--quiet",
                "--dry-run",
            ],
        )
        self.assertEqual(result.exit_code, 0)

    def test_env_file_flag(self) -> None:
        """--env loads a custom .env file."""
        env_file = self.tmp / "custom.env"
        env_file.write_text("LOG_LEVEL=DEBUG\n")
        with mock.patch("orchestration.config.load_dotenv"):
            with mock.patch.dict(
                "os.environ",
                {"GROQ_API_KEY": "sk-test", "PROCESSED_DATA_PATH": str(self.tmp)},
                clear=True,
            ):
                result = self.runner.invoke(
                    cli,
                    [
                        "--env",
                        str(env_file),
                        "--data",
                        str(self.data_csv),
                        "--tags",
                        str(self.tags_csv),
                        "ingest",
                        "--dry-run",
                    ],
                )
                self.assertEqual(result.exit_code, 0)


if __name__ == "__main__":
    unittest.main()
