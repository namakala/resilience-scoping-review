"""Unit tests for hybrid retrieval (pure version, no DB mocks).

Tests call ``hybrid_retrieve()`` with in-memory data dicts and graphs.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(
    0, str(Path(__file__).parent.parent.parent.parent / "src" / "python")
)  # noqa: E402

import networkx as nx  # noqa: E402
import numpy as np  # noqa: E402
import polars as pl  # noqa: E402
from semantic.index_builder import build_index  # noqa: E402
from semantic.retrieval.api import hybrid_retrieve  # noqa: E402
from semantic.retrieval.candidates import resolve_candidate_ids  # noqa: E402
from semantic.retrieval.scoring import (  # noqa: E402
    get_bm25_scores_for_candidates,
    get_depth,
    get_embedding_scores,
)
from semantic.retrieval.weights import select_weights  # noqa: E402


def _make_ontology_graph(tag_depths: dict[str, int]) -> nx.DiGraph:
    G = nx.DiGraph()
    for tag, depth in tag_depths.items():
        G.add_node(tag, depth=depth)
    if "root" in tag_depths:
        for tag, depth in tag_depths.items():
            if depth > 0:
                parent = ".".join(tag.split(".")[:-1]) or "root"
                if parent in G:
                    G.add_edge(parent, tag)
    return G


def _make_bm25_index(exemplar_keywords: dict[int, list[str]]) -> dict:
    rows = []
    kw_id = 0
    for eid, kws in exemplar_keywords.items():
        for kw in kws:
            kw_id += 1
            rows.append((kw_id, eid, kw, 1))
    df = pl.DataFrame(
        {
            "keyword_id": [r[0] for r in rows],
            "exemplar_id": [r[1] for r in rows],
            "keyword_text": [r[2] for r in rows],
            "frequency": [r[3] for r in rows],
        },
        schema={
            "keyword_id": pl.Int64,
            "exemplar_id": pl.Int64,
            "keyword_text": pl.String,
            "frequency": pl.Int32,
        },
    ).lazy()
    result = build_index(df)
    assert isinstance(result, dict)
    return result


TAG_DEPTHS = {"root": 0, "root.child": 1, "root.child.grandchild": 2}
QUERY_EMB = np.array([0.8, 0.6], dtype="float32")


class TestHybridRetrieveExemplars(unittest.TestCase):
    """Exemplar retrieval tests — pure data, no mocks."""

    def test_basic_hybrid_retrieval_exemplars(self):
        emb_map = {
            1: np.array([1.0, 0.0], dtype="float32"),
            2: np.array([0.6, 0.8], dtype="float32"),
            3: np.array([0.0, 1.0], dtype="float32"),
        }
        tag_map = {1: "root.child", 2: "root.child", 3: "root.child.grandchild"}
        bm25 = _make_bm25_index({1: ["stress"], 2: ["coping"], 3: ["resilience"]})
        graph = _make_ontology_graph(TAG_DEPTHS)

        result = hybrid_retrieve(
            query_tag="root",
            query_keywords=["stress"],
            query_embedding=QUERY_EMB,
            candidate_type="exemplar",
            k=50,
            tag_scope_map={"root": {1, 2, 3}},
            tag_entity_map=tag_map,
            bm25_index=bm25,
            embeddings_map=emb_map,
            ontology_graph=graph,
        )

        self.assertEqual(len(result), 3)
        scores = [s for _, s in result]
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_empty_candidate_set(self):
        result = hybrid_retrieve(
            query_tag="root",
            query_keywords=[],
            query_embedding=QUERY_EMB,
            candidate_type="exemplar",
            k=50,
            tag_scope_map={},
            tag_entity_map={},
            bm25_index=_make_bm25_index({}),
            embeddings_map={},
            ontology_graph=_make_ontology_graph(TAG_DEPTHS),
        )
        self.assertEqual(result, [])

    def test_top_k_limit(self):
        emb_map = {i: np.array([0.5, 0.5], dtype="float32") for i in range(1, 11)}
        tag_map = {i: "root.child" for i in range(1, 11)}
        bm25 = _make_bm25_index({i: [f"kw{i}"] for i in range(1, 11)})
        graph = _make_ontology_graph(TAG_DEPTHS)

        result = hybrid_retrieve(
            query_tag="root",
            query_keywords=["test"],
            query_embedding=QUERY_EMB,
            candidate_type="exemplar",
            k=3,
            tag_scope_map={"root": set(range(1, 11))},
            tag_entity_map=tag_map,
            bm25_index=bm25,
            embeddings_map=emb_map,
            ontology_graph=graph,
        )
        self.assertEqual(len(result), 3)

    def test_fewer_than_k_candidates(self):
        emb_map = {42: np.array([0.8, 0.2], dtype="float32")}
        tag_map = {42: "root.child"}
        bm25 = _make_bm25_index({42: ["unique"]})
        graph = _make_ontology_graph(TAG_DEPTHS)

        result = hybrid_retrieve(
            query_tag="root",
            query_keywords=["unique"],
            query_embedding=QUERY_EMB,
            candidate_type="exemplar",
            k=50,
            tag_scope_map={"root": {42}},
            tag_entity_map=tag_map,
            bm25_index=bm25,
            embeddings_map=emb_map,
            ontology_graph=graph,
        )
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0][0], 42)

    def test_proximity_boost(self):
        emb_map = {
            1: np.array([0.5, 0.5], dtype="float32"),
            2: np.array([0.5, 0.5], dtype="float32"),
        }
        tag_map = {1: "root", 2: "root.child"}
        bm25 = _make_bm25_index({1: ["kw"], 2: ["kw"]})
        graph = _make_ontology_graph(TAG_DEPTHS)

        result = hybrid_retrieve(
            query_tag="root",
            query_keywords=["kw"],
            query_embedding=QUERY_EMB,
            candidate_type="exemplar",
            k=2,
            tag_scope_map={"root": {1, 2}},
            tag_entity_map=tag_map,
            bm25_index=bm25,
            embeddings_map=emb_map,
            ontology_graph=graph,
            weights=select_weights("exemplar"),
        )
        self.assertEqual(result[0][0], 1)

    def test_tie_breaking_by_entity_id(self):
        emb_map = {
            10: np.array([0.5, 0.5], dtype="float32"),
            20: np.array([0.5, 0.5], dtype="float32"),
        }
        tag_map = {10: "root.child", 20: "root.child"}
        bm25 = _make_bm25_index({10: ["kw"], 20: ["kw"]})
        graph = _make_ontology_graph(TAG_DEPTHS)

        result = hybrid_retrieve(
            query_tag="root.child",
            query_keywords=["kw"],
            query_embedding=QUERY_EMB,
            candidate_type="exemplar",
            k=2,
            tag_scope_map={"root.child": {10, 20}},
            tag_entity_map=tag_map,
            bm25_index=bm25,
            embeddings_map=emb_map,
            ontology_graph=graph,
        )
        self.assertEqual(result[0][0], 10)
        self.assertEqual(result[1][0], 20)


class TestHybridRetrieveNonExemplar(unittest.TestCase):
    """Non-exemplar (code/theme) retrieval — BM25 skipped, weights adjusted."""

    def test_code_candidate_skips_bm25(self):
        emb_map = {
            10: np.array([1.0, 0.0], dtype="float32"),
            11: np.array([0.0, 1.0], dtype="float32"),
        }
        tag_map = {10: "root.child", 11: "root.child"}
        graph = _make_ontology_graph(TAG_DEPTHS)

        result = hybrid_retrieve(
            query_tag="root",
            query_keywords=[],
            query_embedding=QUERY_EMB,
            candidate_type="code",
            k=5,
            tag_scope_map={"root.child": {10, 11}},
            tag_entity_map=tag_map,
            bm25_index={},
            embeddings_map=emb_map,
            ontology_graph=graph,
        )
        self.assertEqual(len(result), 2)
        # ID 10 has higher emb score than ID 11
        self.assertEqual(result[0][0], 10)

    def test_code_candidate_empty_scope(self):
        result = hybrid_retrieve(
            query_tag="root",
            query_keywords=[],
            query_embedding=QUERY_EMB,
            candidate_type="theme",
            k=5,
            tag_scope_map={},
            tag_entity_map={},
            bm25_index={},
            embeddings_map={},
            ontology_graph=_make_ontology_graph(TAG_DEPTHS),
        )
        self.assertEqual(result, [])

    def test_non_exemplar_all_at_same_depth(self):
        emb_map = {
            1: np.array([1.0, 0.0], dtype="float32"),
            2: np.array([0.6, 0.8], dtype="float32"),
        }
        tag_map = {1: "root.child", 2: "root.child"}
        graph = _make_ontology_graph(TAG_DEPTHS)

        result = hybrid_retrieve(
            query_tag="root.child",
            query_keywords=[],
            query_embedding=QUERY_EMB,
            candidate_type="code",
            k=5,
            tag_scope_map={"root.child": {1, 2}},
            tag_entity_map=tag_map,
            bm25_index={},
            embeddings_map=emb_map,
            ontology_graph=graph,
        )
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0][0], 2)
        self.assertEqual(result[1][0], 1)


class TestGetBM25Scores(unittest.TestCase):
    """Direct tests for get_bm25_scores_for_candidates."""

    def setUp(self):
        lf = pl.DataFrame(
            {
                "keyword_id": [1, 2],
                "exemplar_id": [1, 2],
                "keyword_text": ["stress", "anxiety"],
                "frequency": [1, 1],
            },
            schema={
                "keyword_id": pl.Int64,
                "exemplar_id": pl.Int64,
                "keyword_text": pl.String,
                "frequency": pl.Int32,
            },
        ).lazy()
        self.bm25_index = build_index(lf)

    def test_returns_top_k(self):
        result = get_bm25_scores_for_candidates(
            ["stress"],
            {1, 2},
            k=1,
            bm25_index=self.bm25_index,
        )
        self.assertEqual(len(result), 1)
        self.assertIn(1, result)

    def test_filters_by_candidate_ids(self):
        result = get_bm25_scores_for_candidates(
            ["anxiety"],
            {2},
            k=5,
            bm25_index=self.bm25_index,
        )
        self.assertEqual(len(result), 1)
        self.assertIn(2, result)

    def test_empty_candidate_set(self):
        result = get_bm25_scores_for_candidates(
            ["stress"],
            set(),
            k=5,
            bm25_index=self.bm25_index,
        )
        self.assertEqual(result, {})


class TestGetEmbeddingScores(unittest.TestCase):
    """Direct tests for get_embedding_scores."""

    def test_cosine_similarity(self):
        query = np.array([1.0, 0.0], dtype=np.float32)
        emb_map = {
            1: np.array([1.0, 0.0], dtype=np.float32),
            2: np.array([0.0, 1.0], dtype=np.float32),
        }
        scores, top_set = get_embedding_scores(query, emb_map, k=2)
        self.assertIn(1, scores)
        self.assertIn(2, scores)
        self.assertGreater(scores[1], scores[2])

    def test_top_k_limits(self):
        query = np.array([1.0, 0.0], dtype=np.float32)
        emb_map = {i: np.array([1.0, 0.0], dtype=np.float32) for i in range(1, 6)}
        _, top_set = get_embedding_scores(query, emb_map, k=3)
        self.assertEqual(len(top_set), 3)

    def test_empty_map(self):
        scores, top_set = get_embedding_scores(
            np.array([1.0, 0.0], dtype=np.float32),
            {},
            k=5,
        )
        self.assertEqual(scores, {})
        self.assertEqual(top_set, set())


class TestGetDepth(unittest.TestCase):
    """Direct tests for get_depth."""

    def test_root_depth(self):
        G = nx.DiGraph()
        G.add_node("root", depth=0)
        self.assertEqual(get_depth("root", G), 0)

    def test_known_tag(self):
        G = nx.DiGraph()
        G.add_node("root.A.B", depth=2)
        self.assertEqual(get_depth("root.A.B", G), 2)

    def test_unknown_tag(self):
        G = nx.DiGraph()
        self.assertEqual(get_depth("nonexistent", G), 0)


class TestResolveCandidateIds(unittest.TestCase):
    """Direct tests for resolve_candidate_ids."""

    def test_exemplar_returns_all_from_entity_map(self):
        tag_map = {1: "root.A", 2: "root.A", 3: "root.B"}
        ids, tag_out = resolve_candidate_ids(
            candidate_type="exemplar",
            tag_scope_map={},
            tag_entity_map=tag_map,
        )
        self.assertEqual(ids, {1, 2, 3})
        self.assertEqual(tag_out, tag_map)

    def test_non_exemplar_uses_scope_map(self):
        scope = {"root.A": {10, 11}, "root.B": {20}}
        ids, _ = resolve_candidate_ids(
            candidate_type="code",
            tag_scope_map=scope,
            tag_entity_map={},
        )
        self.assertEqual(ids, {10, 11, 20})

    def test_empty_scope(self):
        ids, _ = resolve_candidate_ids(
            candidate_type="code",
            tag_scope_map={},
            tag_entity_map={},
        )
        self.assertEqual(ids, set())


if __name__ == "__main__":
    unittest.main()
