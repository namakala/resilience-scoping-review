"""Tests for inference/prompts.py — template loading and rendering."""

# flake8: noqa: E402
import sys
import unittest
from pathlib import Path

sys.path.insert(
    0, str(Path(__file__).parent.parent.parent.parent / "src" / "python")
)  # noqa: E402

from inference.prompts import (  # noqa: E402
    PromptBundle,
    render_code_prompt,
    render_interpretation_prompt,
    render_theme_prompt,
)


class TestPromptTemplates(unittest.TestCase):
    """Verify each Jinja2 template renders without errors and replaces
    all placeholders."""

    # -- helpers ---------------------------------------------------------

    def assert_no_unrendered_placeholders(self, text: str):
        """Fail if any Jinja2 placeholder remains in the rendered text."""
        self.assertNotIn("{{", text, msg="Unrendered placeholder found")

    def assert_contains_required_keys(self, text: str, keys: list[str]):
        """Assert the rendered text mentions all required output field
        names."""
        for key in keys:
            self.assertIn(key, text, msg=f"Missing expected key: {key}")

    def assert_is_prompt_bundle(self, obj):
        """Assert the return value is a PromptBundle."""
        self.assertIsInstance(obj, PromptBundle)

    # -- code_inference.j2 ------------------------------------------------

    def test_code_prompt_renders_with_exemplars(self):
        bundle = render_code_prompt(
            ontology_path=["root", "tag1", "subtag"],
            tag_description="Codes related to adaptive capacity",
            existing_codes=[
                {
                    "name": "Coping Strategy",
                    "definition": "Short-term " "response to disturbance",
                }
            ],
            exemplars=[
                {
                    "id": "E001",
                    "content": "Community relied on local knowledge.",
                    "keywords": ["local knowledge", "adaptation"],
                }
            ],
        )
        self.assert_is_prompt_bundle(bundle)
        self.assert_no_unrendered_placeholders(bundle.system)
        self.assert_no_unrendered_placeholders(bundle.user)
        self.assert_contains_required_keys(
            bundle.system,
            [
                "code_name",
                "definition",
                "related_existing_codes",
                "exemplar_ids",
            ],
        )
        # Verify wrapper object structure in system prompt
        self.assertIn('"codes"', bundle.system)
        self.assertIn("E001", bundle.user)
        self.assertIn("Coping Strategy", bundle.user)

    def test_code_prompt_empty_existing_codes(self):
        bundle = render_code_prompt(
            ontology_path=["root", "tag1"],
            tag_description="A test tag",
            existing_codes=[],
            exemplars=[
                {
                    "id": "E002",
                    "content": "Sample content.",
                    "keywords": ["sample"],
                }
            ],
        )
        self.assert_is_prompt_bundle(bundle)
        self.assert_no_unrendered_placeholders(bundle.system)
        self.assert_no_unrendered_placeholders(bundle.user)
        self.assertIn("No existing codes", bundle.user)

    def test_code_prompt_empty_exemplars(self):
        bundle = render_code_prompt(
            ontology_path=["root"],
            tag_description="Empty tag",
            existing_codes=[],
            exemplars=[],
        )
        self.assert_is_prompt_bundle(bundle)
        self.assert_no_unrendered_placeholders(bundle.system)
        self.assert_no_unrendered_placeholders(bundle.user)
        self.assert_contains_required_keys(
            bundle.system,
            ["code_name", "definition", "exemplar_ids"],
        )

    # -- theme_inference.j2 ------------------------------------------------

    def test_theme_prompt_renders_with_codes(self):
        bundle = render_theme_prompt(
            tag_name="Adaptive Capacity",
            tag_description="Community ability to adapt",
            ontology_path=["root", "tag1"],
            codes=[
                {
                    "id": "C001",
                    "name": "Local Knowledge",
                    "definition": "Use of indigenous practices",
                    "exemplar_count": 5,
                },
                {
                    "id": "C002",
                    "name": "Resource Sharing",
                    "definition": "Pooling of community assets",
                    "exemplar_count": 3,
                },
            ],
        )
        self.assert_is_prompt_bundle(bundle)
        self.assert_no_unrendered_placeholders(bundle.system)
        self.assert_no_unrendered_placeholders(bundle.user)
        self.assert_contains_required_keys(
            bundle.system,
            ["theme_name", "narrative", "code_ids"],
        )
        self.assertIn('"themes"', bundle.system)
        self.assertIn("C001", bundle.user)
        self.assertIn("C002", bundle.user)
        self.assertIn("Adaptive Capacity", bundle.user)

    def test_theme_prompt_single_code(self):
        bundle = render_theme_prompt(
            tag_name="Isolated Tag",
            tag_description="Tag with only one code",
            ontology_path=["root"],
            codes=[
                {
                    "id": "C003",
                    "name": "Solitary Code",
                    "definition": "Only one code exists",
                    "exemplar_count": 1,
                }
            ],
        )
        self.assert_is_prompt_bundle(bundle)
        self.assert_no_unrendered_placeholders(bundle.system)
        self.assert_no_unrendered_placeholders(bundle.user)
        self.assert_contains_required_keys(
            bundle.system,
            ["theme_name", "code_ids"],
        )

    # -- interpretation_synthesis.j2 ---------------------------------------

    def test_interpretation_prompt_renders(self):
        bundle = render_interpretation_prompt(
            tag_hierarchy=[
                ["root", "tag1"],
                ["root", "tag2"],
            ],
            ontology_subtree="root\\n  tag1\\n  tag2",
            themes_by_tag={
                "tag1": [
                    {
                        "theme_name": "Community Cohesion",
                        "narrative": "Bonding mechanisms",
                        "code_ids": ["C001", "C002"],
                    }
                ],
                "tag2": [
                    {
                        "theme_name": "External Support",
                        "narrative": "Outside aid reliance",
                        "code_ids": ["C003"],
                    }
                ],
            },
        )
        self.assert_is_prompt_bundle(bundle)
        self.assert_no_unrendered_placeholders(bundle.system)
        self.assert_no_unrendered_placeholders(bundle.user)
        self.assert_contains_required_keys(
            bundle.system,
            [
                "interpretation_name",
                "narrative",
                "theme_ids",
                "key_insights",
            ],
        )
        self.assertIn('"interpretations"', bundle.system)
        self.assertIn("Community Cohesion", bundle.user)
        self.assertIn("External Support", bundle.user)
        self.assertIn("tag1", bundle.user)
        self.assertIn("tag2", bundle.user)

    def test_interpretation_prompt_empty_themes(self):
        bundle = render_interpretation_prompt(
            tag_hierarchy=[["root", "tag1"]],
            ontology_subtree="root\\n  tag1",
            themes_by_tag={},
        )
        self.assert_is_prompt_bundle(bundle)
        self.assert_no_unrendered_placeholders(bundle.system)
        self.assert_no_unrendered_placeholders(bundle.user)
        self.assert_contains_required_keys(
            bundle.system,
            ["interpretation_name", "narrative", "key_insights"],
        )

    # -- few-shot integration ------------------------------------------------

    def _sample_fewshot(self):
        return [
            {"user": "Example input", "assistant": '{"codes": []}'},
            {"user": "Another input", "assistant": '{"themes": []}'},
        ]

    def test_code_prompt_with_fewshot(self):
        bundle = render_code_prompt(
            fewshot=self._sample_fewshot(),
            ontology_path=["root"],
            tag_description="Test",
            existing_codes=[],
            exemplars=[{"id": "E001", "content": "test", "keywords": ["t"]}],
        )
        self.assertIsNotNone(bundle.fewshot)
        self.assertEqual(len(bundle.fewshot), 2)
        self.assertEqual(bundle.fewshot[0]["user"], "Example input")

    def test_code_prompt_without_fewshot_defaults_none(self):
        bundle = render_code_prompt(
            ontology_path=["root"],
            tag_description="Test",
            existing_codes=[],
            exemplars=[{"id": "E001", "content": "test", "keywords": ["t"]}],
        )
        self.assertIsNone(bundle.fewshot)

    def test_theme_prompt_with_fewshot(self):
        bundle = render_theme_prompt(
            fewshot=self._sample_fewshot(),
            tag_name="Test",
            tag_description="Test tag",
            ontology_path=["root"],
            codes=[{"id": "C001", "name": "C", "definition": "D", "exemplar_count": 1}],
        )
        self.assertIsNotNone(bundle.fewshot)
        self.assertEqual(len(bundle.fewshot), 2)

    def test_theme_prompt_without_fewshot_defaults_none(self):
        bundle = render_theme_prompt(
            tag_name="Test",
            tag_description="Test tag",
            ontology_path=["root"],
            codes=[{"id": "C001", "name": "C", "definition": "D", "exemplar_count": 1}],
        )
        self.assertIsNone(bundle.fewshot)

    def test_interpretation_prompt_with_fewshot(self):
        bundle = render_interpretation_prompt(
            fewshot=self._sample_fewshot(),
            tag_hierarchy=[["root", "t1"]],
            ontology_subtree="root\n  t1",
            themes_by_tag={"t1": []},
        )
        self.assertIsNotNone(bundle.fewshot)
        self.assertEqual(len(bundle.fewshot), 2)

    def test_interpretation_prompt_without_fewshot_defaults_none(self):
        bundle = render_interpretation_prompt(
            tag_hierarchy=[["root", "t1"]],
            ontology_subtree="root\n  t1",
            themes_by_tag={"t1": []},
        )
        self.assertIsNone(bundle.fewshot)


if __name__ == "__main__":
    unittest.main()
