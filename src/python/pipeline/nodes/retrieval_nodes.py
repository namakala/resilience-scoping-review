"""Node: retrieve_candidates — hybrid BM25 + embedding + ontology retrieval."""

from pipeline.config import Config


def retrieve_candidates(
    embed_exemplars: dict,
    embed_keywords: dict,
    build_bm25: dict,
    build_ontology: dict,
    config: Config,
) -> list:
    """Run hybrid retrieval to rank candidate exemplars per tag.

    Combines BM25 lexical scores, embedding cosine similarity, and ontology
    proximity into a single ranked list.
    """
    return []
