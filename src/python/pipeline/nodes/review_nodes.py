"""Nodes: review_codes, review_themes, review_interpretations — HITL stubs."""

from pipeline.config import Config


def review_codes(infer_codes: list, config: Config) -> list:
    """Human-in-the-loop validation of inferred codes.

    Stub: returns input unchanged. Real implementation will prompt user.
    """
    return infer_codes


def review_themes(infer_themes: list, config: Config) -> list:
    """Human-in-the-loop validation of inferred themes.

    Stub: returns input unchanged.
    """
    return infer_themes


def review_interpretations(infer_interpretations: list, config: Config) -> list:
    """Human-in-the-loop validation of inferred interpretations.

    Stub: returns input unchanged.
    """
    return infer_interpretations
