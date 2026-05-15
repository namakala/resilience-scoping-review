"""Nodes: export formatting — codes, themes, interpretations.

Pure functions that format in-memory results into JSON-compatible dict
structures.  No file I/O — the orchestration layer handles writing.
"""

from __future__ import annotations

from pipeline.config import Config

__all__ = [
    "export_codes",
    "export_themes",
    "export_interpretations",
    "export_combined",
    "export_summary",
]


def export_codes(review_codes: list, config: Config) -> dict:
    """Format approved codes as a JSON-compatible dict."""
    return {"codes": review_codes, "count": len(review_codes)}


def export_themes(review_themes: list, config: Config) -> dict:
    """Format approved themes with nested code references."""
    return {"themes": review_themes, "count": len(review_themes)}


def export_interpretations(review_interpretations: list, config: Config) -> dict:
    """Format approved interpretations with nested theme references."""
    return {
        "interpretations": review_interpretations,
        "count": len(review_interpretations),
    }


def export_combined(
    export_codes: dict,
    export_themes: dict,
    export_interpretations: dict,
    config: Config,
) -> dict:
    """Merge all exports into a single hierarchical structure."""
    return {
        "codes": export_codes.get("codes", []),
        "themes": export_themes.get("themes", []),
        "interpretations": export_interpretations.get("interpretations", []),
    }


def export_summary(export_combined: dict, config: Config) -> dict:
    """Counts and provenance for the final output."""
    return {
        "code_count": len(export_combined.get("codes", [])),
        "theme_count": len(export_combined.get("themes", [])),
        "interpretation_count": len(export_combined.get("interpretations", [])),
    }
