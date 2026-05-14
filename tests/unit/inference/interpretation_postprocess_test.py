"""Unit tests for inference/interpretation_postprocess.py — pure validators."""

# flake8: noqa: E402
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "src" / "python"))

from inference.interpretation_postprocess import (
    dedup_interpretation_names,
    flag_overlapping_themes,
    validate_theme_ids_exist,
)
from inference.parsing import InterpretationInference


def _make_interp(name, theme_ids, narrative="n", key_insights=None):
    return InterpretationInference(
        interpretation_name=name,
        narrative=narrative,
        theme_ids=theme_ids,
        key_insights=key_insights or ["insight"],
    )


class TestDedupInterpretationNames(unittest.TestCase):
    """dedup_interpretation_names: append _1, _2 on name collision."""

    def test_no_duplicates_passes_through(self):
        interps = [
            _make_interp("InterpA", ["T1", "T2"]),
            _make_interp("InterpB", ["T3", "T4"]),
        ]
        result = dedup_interpretation_names(interps)
        self.assertEqual(
            [i.interpretation_name for i in result], ["InterpA", "InterpB"]
        )

    def test_sequential_duplicates_appends_counter(self):
        interps = [
            _make_interp("A", ["T1", "T2"]),
            _make_interp("A", ["T3", "T4"]),
            _make_interp("A", ["T5", "T6"]),
        ]
        result = dedup_interpretation_names(interps)
        self.assertEqual([i.interpretation_name for i in result], ["A", "A_1", "A_2"])

    def test_non_sequential_collision(self):
        interps = [
            _make_interp("A", ["T1", "T2"]),
            _make_interp("A_1", ["T3", "T4"]),
            _make_interp("A", ["T5", "T6"]),
        ]
        result = dedup_interpretation_names(interps)
        self.assertEqual([i.interpretation_name for i in result], ["A", "A_1", "A_2"])

    def test_single_interp_no_rename(self):
        interps = [_make_interp("A", ["T1", "T2"])]
        result = dedup_interpretation_names(interps)
        self.assertEqual(result[0].interpretation_name, "A")

    def test_empty_list(self):
        result = dedup_interpretation_names([])
        self.assertEqual(result, [])


class TestFlagOverlappingThemes(unittest.TestCase):
    """flag_overlapping_themes: warn when two interps share a theme_id."""

    def test_no_overlap_no_warning(self):
        interps = [
            _make_interp("A", ["T1", "T2"]),
            _make_interp("B", ["T3", "T4"]),
        ]
        result = flag_overlapping_themes(interps)
        self.assertEqual(len(result), 2)

    def test_overlap_logs_warning(self):
        interps = [
            _make_interp("A", ["T1", "T2"]),
            _make_interp("B", ["T2", "T3"]),
        ]
        with self.assertLogs(
            "inference.interpretation_postprocess", level="WARNING"
        ) as logs:
            result = flag_overlapping_themes(interps)
        self.assertTrue(any("T2" in m for m in logs.output))

    def test_multiple_overlaps(self):
        interps = [
            _make_interp("A", ["T1", "T2"]),
            _make_interp("B", ["T2", "T3"]),
            _make_interp("C", ["T3", "T4"]),
        ]
        with self.assertLogs(
            "inference.interpretation_postprocess", level="WARNING"
        ) as logs:
            result = flag_overlapping_themes(interps)
        self.assertGreaterEqual(len(logs.output), 2)


class TestValidateThemeIdsExist(unittest.TestCase):
    """validate_theme_ids_exist: warn on theme_id outside valid set."""

    def test_all_valid_no_warning(self):
        interps = [_make_interp("A", ["1", "2"])]
        result = validate_theme_ids_exist(interps, {"1", "2"})
        self.assertEqual(len(result), 1)

    def test_invalid_theme_id_logs_warning(self):
        interps = [_make_interp("A", ["1", "99"])]
        with self.assertLogs(
            "inference.interpretation_postprocess", level="WARNING"
        ) as logs:
            validate_theme_ids_exist(interps, {"1", "2"})
        self.assertTrue(any("99" in m for m in logs.output))

    def test_empty_interps_no_warning(self):
        validate_theme_ids_exist([], {"1", "2"})


if __name__ == "__main__":
    unittest.main()
