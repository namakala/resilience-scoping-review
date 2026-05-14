"""Nodes: build_bm25, build_ontology — construct lexical and graph indices."""

from pipeline.config import Config


def build_bm25(load_artifacts: dict, config: Config) -> dict:
    """Build BM25 lexical index over extracted keywords."""
    return {"corpus_size": 0, "tokenizer_config": config.bm25_tokenizer_config}


def build_ontology(load_artifacts: dict, config: Config) -> dict:
    """Build tag ontology graph from loaded tags."""
    return {"node_count": 0, "edge_count": 0}
