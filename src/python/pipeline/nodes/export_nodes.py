"""Node: export — write final results to disk."""

from pipeline.config import Config


def export(review_interpretations: list, config: Config) -> dict:
    """Export final hierarchical results to disk (JSON, CSV, Markdown).

    Returns a summary dict with output paths and statistics.
    """
    return {
        "output_format": "json",
        "interpretation_count": len(review_interpretations),
        "paths": [],
    }
