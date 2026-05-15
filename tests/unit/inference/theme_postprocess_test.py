"""Unit tests for inference/theme_postprocess.py — pure validators."""

# flake8: noqa: E402
import sys
import unittest
from pathlib import Path

sys.path.insert(
    0, str(Path(__file__).parent.parent.parent.parent / "src" / "python")
)  # noqa: E402

from inference.parsing import ThemeInference  # noqa: E402
from inference.theme_postprocess import (  # noqa: E402
    dedup_theme_names,
    flag_small_themes,
    validate_code_belonging,
)


def _make_theme(name, code_ids, narrative="n"):
    return ThemeInference(theme_name=name, narrative=narrative, code_ids=code_ids)


class TestDedupThemeNames(unittest.TestCase):
    """dedup_theme_names: append _1, _2 on name collision."""

    def test_no_duplicates_passes_through(self):
        themes = [
            _make_theme("A", ["1", "2"]),
            _make_theme("B", ["3", "4"]),
        ]
        result = dedup_theme_names(themes)
        self.assertEqual([t.theme_name for t in result], ["A", "B"])

    def test_sequential_duplicates_appends_counter(self):
        themes = [
            _make_theme("A", ["1", "2"]),
            _make_theme("A", ["3", "4"]),
            _make_theme("A", ["5", "6"]),
        ]
        result = dedup_theme_names(themes)
        self.assertEqual([t.theme_name for t in result], ["A", "A_1", "A_2"])

    def test_non_sequential_collision(self):
        themes = [
            _make_theme("A", ["1", "2"]),
            _make_theme("A_1", ["3", "4"]),
            _make_theme("A", ["5", "6"]),
        ]
        result = dedup_theme_names(themes)
        self.assertEqual([t.theme_name for t in result], ["A", "A_1", "A_2"])

    def test_single_theme_no_rename(self):
        themes = [_make_theme("A", ["1", "2"])]
        result = dedup_theme_names(themes)
        self.assertEqual(result[0].theme_name, "A")

    def test_empty_list(self):
        result = dedup_theme_names([])
        self.assertEqual(result, [])


class TestFlagSmallThemes(unittest.TestCase):
    """flag_small_themes: warn on <2 codes, pass through on >=2."""

    def test_two_codes_no_warning(self):
        themes = [_make_theme("A", ["1", "2"])]
        result = flag_small_themes(themes)
        self.assertEqual(len(result), 1)

    def test_one_code_logs_warning(self):
        themes = [_make_theme("A", ["1"])]
        with self.assertLogs("inference.theme_postprocess", level="WARNING") as logs:
            result = flag_small_themes(themes)
        self.assertEqual(len(result), 1)
        self.assertTrue(any("flagged for review" in m for m in logs.output))

    def test_zero_codes_logs_warning(self):
        themes = [_make_theme("A", [])]
        with self.assertLogs("inference.theme_postprocess", level="WARNING") as logs:
            result = flag_small_themes(themes)
        self.assertEqual(len(result), 1)
        self.assertTrue(any("flagged for review" in m for m in logs.output))

    def test_mixed_sizes(self):
        themes = [
            _make_theme("Big", ["1", "2", "3"]),
            _make_theme("Small", ["4"]),
            _make_theme("Tiny", []),
        ]
        with self.assertLogs("inference.theme_postprocess", level="WARNING") as logs:
            result = flag_small_themes(themes)
        self.assertEqual(len(result), 3)
        self.assertEqual(len(logs.output), 2)

    def test_empty_list_no_warning(self):
        result = flag_small_themes([])
        self.assertEqual(result, [])


class TestValidateCodeBelonging(unittest.TestCase):
    """validate_code_belonging: warn on cross-batch code IDs."""

    def test_all_within_batch_no_warning(self):
        themes = [_make_theme("A", ["1", "2"])]
        validate_code_belonging(themes, {"1", "2"}, "batch_00")

    def test_extraneous_code_id_logs_warning(self):
        themes = [_make_theme("A", ["1", "99"])]
        with self.assertLogs("inference.theme_postprocess", level="WARNING") as logs:
            validate_code_belonging(themes, {"1", "2"}, "batch_00")
        self.assertEqual(len(logs.output), 1)
        self.assertIn("99", logs.output[0])

    def test_multiple_extraneous_ids(self):
        themes = [
            _make_theme("A", ["1", "99"]),
            _make_theme("B", ["98"]),
        ]
        with self.assertLogs("inference.theme_postprocess", level="WARNING") as logs:
            validate_code_belonging(themes, {"1", "2"}, "batch_00")
        self.assertEqual(len(logs.output), 2)

    def test_empty_themes_no_warning(self):
        validate_code_belonging([], {"1"}, "batch_00")


if __name__ == "__main__":
    unittest.main()
