"""Tests for _validate_params in inference/inference_status_types.py."""

# flake8: noqa: E402
import sys
import unittest
from pathlib import Path

sys.path.insert(
    0,
    str(Path(__file__).parent.parent.parent.parent / "src" / "python"),
)

from inference.inference_status_types import STAGE_CODE, _validate_params


class TestValidation(unittest.TestCase):
    """Input validation for _validate_params."""

    def test_empty_entity_id(self):
        with self.assertRaises(ValueError):
            _validate_params("", "exemplar", STAGE_CODE, "pending")

    def test_whitespace_entity_id(self):
        with self.assertRaises(ValueError):
            _validate_params("   ", "exemplar", STAGE_CODE, "pending")

    def test_invalid_entity_type(self):
        with self.assertRaises(ValueError):
            _validate_params("e1", "widget", STAGE_CODE, "pending")

    def test_invalid_stage(self):
        with self.assertRaises(ValueError):
            _validate_params("e1", "exemplar", "staging", "pending")

    def test_invalid_status(self):
        with self.assertRaises(ValueError):
            _validate_params("e1", "exemplar", STAGE_CODE, "unknown")

    def test_non_string_entity_id(self):
        with self.assertRaises(ValueError):
            _validate_params(123, "exemplar", STAGE_CODE, "pending")

    def test_invalid_stage_from_crud(self):
        from inference.inference_status_crud import set_status

        with self.assertRaises(ValueError):
            set_status(None, "e1", "exemplar", "bad_stage", "pending")


if __name__ == "__main__":
    unittest.main()
