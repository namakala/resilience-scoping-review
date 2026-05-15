"""Nodes: export formatting — codes, themes, interpretations.

Pure functions that format in-memory results into JSON-compatible dict
structures.  Flat lists only — the orchestration layer builds the
hierarchical JSON and writes files.  See ``orchestration/export.py``.
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
    """Wrap approved codes in ``{codes: [...], count: N}``."""
    return {"codes": list(review_codes), "count": len(review_codes)}


def export_themes(review_themes: list, config: Config) -> dict:
    """Wrap approved themes in ``{themes: [...], count: N}``."""
    return {"themes": list(review_themes), "count": len(review_themes)}


def export_interpretations(review_interpretations: list, config: Config) -> dict:
    """Wrap approved interpretations in ``{interpretations: [...], count: N}``."""
    return {
        "interpretations": list(review_interpretations),
        "count": len(review_interpretations),
    }


def export_combined(
    export_codes: dict,
    export_themes: dict,
    export_interpretations: dict,
    config: Config,
) -> dict:
    """Merge flat lists into a single output dict with summary."""
    codes = list(export_codes.get("codes", []))
    themes = list(export_themes.get("themes", []))
    interps = list(export_interpretations.get("interpretations", []))
    return {
        "codes": codes,
        "themes": themes,
        "interpretations": interps,
        "summary": {
            "code_count": len(codes),
            "theme_count": len(themes),
            "interpretation_count": len(interps),
        },
    }


def export_summary(export_combined: dict, config: Config) -> dict:
    """Counts and provenance for the final output."""
    return dict(export_combined.get("summary", {}))
