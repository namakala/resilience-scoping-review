"""Tests for inference/prompts.py — template loading and rendering."""

# flake8: noqa: E402
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "src" / "python"))

from inference.prompts import (  # noqa: E402
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

    # -- code_inference.j2 ------------------------------------------------

    def test_code_prompt_renders_with_exemplars(self):
        prompt = render_code_prompt(
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
        self.assert_no_unrendered_placeholders(prompt)
        self.assert_contains_required_keys(
            prompt,
            ["code_name", "definition", "supporting_quote", "related_existing_codes"],
        )
        self.assertIn("E001", prompt)
        self.assertIn("Coping Strategy", prompt)

    def test_code_prompt_empty_existing_codes(self):
        prompt = render_code_prompt(
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
        self.assert_no_unrendered_placeholders(prompt)
        self.assertIn("No existing codes", prompt)

    def test_code_prompt_empty_exemplars(self):
        prompt = render_code_prompt(
            ontology_path=["root"],
            tag_description="Empty tag",
            existing_codes=[],
            exemplars=[],
        )
        self.assert_no_unrendered_placeholders(prompt)
        self.assert_contains_required_keys(
            prompt,
            ["code_name", "definition", "supporting_quote"],
        )

    # -- theme_inference.j2 ------------------------------------------------

    def test_theme_prompt_renders_with_codes(self):
        prompt = render_theme_prompt(
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
        self.assert_no_unrendered_placeholders(prompt)
        self.assert_contains_required_keys(
            prompt,
            ["theme_name", "narrative", "code_ids"],
        )
        self.assertIn("C001", prompt)
        self.assertIn("C002", prompt)
        self.assertIn("Adaptive Capacity", prompt)

    def test_theme_prompt_single_code(self):
        prompt = render_theme_prompt(
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
        self.assert_no_unrendered_placeholders(prompt)
        self.assert_contains_required_keys(
            prompt,
            ["theme_name", "code_ids"],
        )

    # -- interpretation_synthesis.j2 ---------------------------------------

    def test_interpretation_prompt_renders(self):
        prompt = render_interpretation_prompt(
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
        self.assert_no_unrendered_placeholders(prompt)
        self.assert_contains_required_keys(
            prompt,
            [
                "interpretation_name",
                "narrative",
                "theme_ids",
                "key_insights",
            ],
        )
        self.assertIn("Community Cohesion", prompt)
        self.assertIn("External Support", prompt)
        self.assertIn("tag1", prompt)
        self.assertIn("tag2", prompt)

    def test_interpretation_prompt_empty_themes(self):
        prompt = render_interpretation_prompt(
            tag_hierarchy=[["root", "tag1"]],
            ontology_subtree="root\\n  tag1",
            themes_by_tag={},
        )
        self.assert_no_unrendered_placeholders(prompt)
        self.assert_contains_required_keys(
            prompt,
            ["interpretation_name", "narrative", "key_insights"],
        )


if __name__ == "__main__":
    unittest.main()
