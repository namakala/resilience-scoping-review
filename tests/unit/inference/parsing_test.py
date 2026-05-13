"""Tests for inference/parsing.py — response parsing and validation."""

# flake8: noqa: E402
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "src" / "python"))

from inference.parsing import (
    CodeInference,
    InterpretationInference,
    ThemeInference,
    _strip_fences,
    _unwrap,
    parse_code_response,
    parse_interpretation_response,
    parse_theme_response,
)
from utils.exceptions import ParseError


class TestStripFences(unittest.TestCase):
    """Markdown code fence removal."""

    def test_no_fence(self):
        self.assertEqual(_strip_fences("hello"), "hello")

    def test_fenced_with_json_tag(self):
        raw = '```json\n{"key": "value"}\n```'
        self.assertEqual(_strip_fences(raw), '{"key": "value"}')

    def test_fenced_without_tag(self):
        raw = '```\n{"key": "value"}\n```'
        self.assertEqual(_strip_fences(raw), '{"key": "value"}')

    def test_fence_on_same_line(self):
        raw = '```json {"key": "value"} ```'
        self.assertEqual(_strip_fences(raw), '{"key": "value"}')


class TestUnwrap(unittest.TestCase):
    """Wrapper key extraction."""

    def test_valid_unwrap(self):
        data = {"codes": [{"id": 1}, {"id": 2}]}
        self.assertEqual(_unwrap(data, "codes"), [{"id": 1}, {"id": 2}])

    def test_missing_key(self):
        data = {"other": []}
        with self.assertRaises(ParseError):
            _unwrap(data, "codes")

    def test_not_a_list(self):
        data = {"codes": "not_a_list"}
        with self.assertRaises(ParseError):
            _unwrap(data, "codes")


class TestParseCodeResponse(unittest.TestCase):
    """End-to-end code inference response parsing."""

    VALID_JSON = """{
        "codes": [
            {
                "exemplar_id": "E001",
                "code_name": "Config Drift",
                "definition": "Gradual config degradation",
                "supporting_quote": "crept over time",
                "related_existing_codes": []
            }
        ]
    }"""

    def test_valid(self):
        result = parse_code_response(self.VALID_JSON)
        self.assertEqual(len(result), 1)
        self.assertIsInstance(result[0], CodeInference)
        self.assertEqual(result[0].exemplar_id, "E001")
        self.assertEqual(result[0].code_name, "Config Drift")

    def test_valid_with_fences(self):
        fenced = f"```json\n{self.VALID_JSON}\n```"
        result = parse_code_response(fenced)
        self.assertEqual(len(result), 1)

    def test_valid_empty_array(self):
        result = parse_code_response('{"codes": []}')
        self.assertEqual(len(result), 0)

    def test_invalid_json(self):
        with self.assertRaises(ParseError):
            parse_code_response("{bad json}")

    def test_missing_wrapper_key(self):
        with self.assertRaises(ParseError):
            parse_code_response('{"items": []}')

    def test_array_at_top_level(self):
        with self.assertRaises(ParseError):
            parse_code_response('[{"code_name": "test"}]')

    def test_wrapper_not_a_list(self):
        with self.assertRaises(ParseError):
            parse_code_response('{"codes": "not_a_list"}')

    def test_schema_validation_failure(self):
        with self.assertRaises(ParseError):
            parse_code_response('{"codes": [{"exemplar_id": "E001"}]}')

    def test_preserves_extra_fields(self):
        result = parse_code_response(
            '{"codes": [{"exemplar_id": "E001", "code_name": "N", '
            '"definition": "D", "supporting_quote": "Q", '
            '"extra": "ignored"}]}'
        )
        self.assertEqual(len(result), 1)
        self.assertFalse(hasattr(result[0], "extra"))

    def test_multiple_items(self):
        result = parse_code_response(
            """{
            "codes": [
                {
                    "exemplar_id": "E001",
                    "code_name": "CodeA",
                    "definition": "DefA",
                    "supporting_quote": "QuoteA"
                },
                {
                    "exemplar_id": "E002",
                    "code_name": "CodeB",
                    "definition": "DefB",
                    "supporting_quote": "QuoteB",
                    "related_existing_codes": ["CodeA"]
                }
            ]
        }"""
        )
        self.assertEqual(len(result), 2)
        self.assertEqual(result[1].related_existing_codes, ["CodeA"])


class TestParseThemeResponse(unittest.TestCase):
    """Theme inference response parsing."""

    def test_valid(self):
        result = parse_theme_response(
            """{
            "themes": [
                {
                    "theme_name": "Community Bonds",
                    "narrative": "Social cohesion mechanisms",
                    "code_ids": ["C001", "C002"]
                }
            ]
        }"""
        )
        self.assertEqual(len(result), 1)
        self.assertIsInstance(result[0], ThemeInference)
        self.assertEqual(result[0].theme_name, "Community Bonds")

    def test_missing_wrapper(self):
        with self.assertRaises(ParseError):
            parse_theme_response('{"wrong_key": []}')


class TestParseInterpretationResponse(unittest.TestCase):
    """Interpretation synthesis response parsing."""

    def test_valid(self):
        result = parse_interpretation_response(
            """{
            "interpretations": [
                {
                    "interpretation_name": "Cross-cutting Insight",
                    "narrative": "Spans multiple tags",
                    "theme_ids": ["T001", "T002"],
                    "key_insights": ["First", "Second"]
                }
            ]
        }"""
        )
        self.assertEqual(len(result), 1)
        self.assertIsInstance(result[0], InterpretationInference)
        self.assertEqual(result[0].interpretation_name, "Cross-cutting Insight")
        self.assertEqual(result[0].key_insights, ["First", "Second"])


if __name__ == "__main__":
    unittest.main()
