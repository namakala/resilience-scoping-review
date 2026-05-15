"""Tests for inference/fewshot_loader.py — static curated example loading."""

# flake8: noqa: E402
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(
    0, str(Path(__file__).parent.parent.parent.parent / "src" / "python")
)  # noqa: E402

from inference.fewshot_loader import load_fewshot  # noqa: E402


class TestLoadFewshot(unittest.TestCase):
    """Tests for load_fewshot() with the actual on-disk JSON files."""

    # -- known types -------------------------------------------------------

    def test_load_code_inference(self):
        examples = load_fewshot("code_inference", count=2)
        self.assertEqual(len(examples), 2)
        for ex in examples:
            self.assertIn("user", ex)
            self.assertIn("assistant", ex)

    def test_load_theme_inference(self):
        examples = load_fewshot("theme_inference", count=2)
        self.assertEqual(len(examples), 2)
        for ex in examples:
            self.assertIn("user", ex)
            self.assertIn("assistant", ex)

    def test_load_interpretation_synthesis(self):
        examples = load_fewshot("interpretation_synthesis", count=2)
        self.assertEqual(len(examples), 2)
        for ex in examples:
            self.assertIn("user", ex)
            self.assertIn("assistant", ex)

    # -- count param -------------------------------------------------------

    def test_count_zero_returns_empty(self):
        examples = load_fewshot("code_inference", count=0)
        self.assertEqual(examples, [])

    def test_count_exceeds_available_returns_all(self):
        examples = load_fewshot("code_inference", count=999)
        self.assertGreater(len(examples), 2)

    # -- missing type ------------------------------------------------------

    def test_unknown_type_returns_empty(self):
        examples = load_fewshot("nonexistent_type", count=2)
        self.assertEqual(examples, [])

    # -- shuffle -----------------------------------------------------------

    def test_shuffle_does_not_change_count(self):
        examples = load_fewshot("code_inference", count=2, shuffle=True)
        self.assertEqual(len(examples), 2)

    # -- isolated temp file (no dependency on on-disk data) ----------------

    def test_with_temp_file(self):
        data = [
            {"user": "u1", "assistant": "a1"},
            {"user": "u2", "assistant": "a2"},
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "test_type.json"
            path.write_text(json.dumps(data))
            # Monkey-patch the _FEWSHOT_DIR
            import inference.fewshot_loader as fl

            original = fl._FEWSHOT_DIR
            fl._FEWSHOT_DIR = str(tmpdir)
            try:
                examples = load_fewshot("test_type", count=2)
                self.assertEqual(len(examples), 2)
                self.assertEqual(examples[0]["user"], "u1")
                self.assertEqual(examples[1]["assistant"], "a2")
            finally:
                fl._FEWSHOT_DIR = original

    def test_with_temp_file_count_limited(self):
        data = [
            {"user": "u1", "assistant": "a1"},
            {"user": "u2", "assistant": "a2"},
            {"user": "u3", "assistant": "a3"},
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "other_type.json"
            path.write_text(json.dumps(data))
            import inference.fewshot_loader as fl

            original = fl._FEWSHOT_DIR
            fl._FEWSHOT_DIR = str(tmpdir)
            try:
                examples = load_fewshot("other_type", count=2)
                self.assertEqual(len(examples), 2)
            finally:
                fl._FEWSHOT_DIR = original


if __name__ == "__main__":
    unittest.main()
