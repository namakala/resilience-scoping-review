"""Nodes: init_groq_client, infer_codes, infer_themes, infer_interpretations."""

from pipeline.config import Config


def init_groq_client(config: Config) -> dict:
    """Initialise the Groq LLM client.

    Returns a dict with client metadata as a lightweight stub.
    """
    return {"model": config.groq_model, "timeout": config.groq_timeout}


def infer_codes(
    retrieve_candidates: list,
    init_groq_client: dict,
    build_ontology: dict,
    config: Config,
) -> list:
    """Run batch Groq inference to generate codes from exemplars."""
    return []


def infer_themes(
    review_codes: list,
    build_ontology: dict,
    config: Config,
) -> list:
    """Run batch Groq inference to aggregate codes into themes per tag."""
    return []


def infer_interpretations(
    review_themes: list,
    build_ontology: dict,
    config: Config,
) -> list:
    """Run batch Groq inference to synthesise interpretations across tags."""
    return []
