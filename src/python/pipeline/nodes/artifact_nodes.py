"""Node: load_artifacts — load exemplars, tags, keywords from Parquet."""

from pipeline.config import Config


def load_artifacts(config: Config) -> dict:
    """Load all immutable artifacts (exemplars, tags, keywords) from disk.

    Returns a dict with keys ``exemplars``, ``tags``, ``keywords`` mapping to
    Polars LazyFrames (or empty placeholders for stub).
    """
    return {
        "exemplars": None,
        "tags": None,
        "keywords": None,
    }
