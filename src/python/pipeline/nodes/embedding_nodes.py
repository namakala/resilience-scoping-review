"""Nodes: init_embedding_model, embed_exemplars, embed_keywords."""

from pipeline.config import Config


def init_embedding_model(config: Config) -> str:
    """Initialise (or stub) the sentence-transformer embedding model.

    Returns the model name string as a lightweight placeholder.
    """
    return config.embedding_model


def embed_exemplars(load_artifacts: dict, config: Config) -> dict:
    """Generate embeddings for all exemplars."""
    return {"embeddings": [], "entity_type": "exemplar"}


def embed_keywords(load_artifacts: dict, config: Config) -> dict:
    """Generate embeddings for all keywords."""
    return {"embeddings": [], "entity_type": "keyword"}
