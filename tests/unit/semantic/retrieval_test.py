"""Unit tests for hybrid retrieval pipeline (Feature 28).

Covers:
- Basic exemplar retrieval with BM25 + embedding + rerank
- Non-exemplar candidate types (BM25 skipped, renormalized weights)
- Proximity boost computation (same tag vs distant tag)
- Deterministic ordering with tie-breaking by entity_id
- Top-k limiting and edge cases (empty set, fewer than k candidates)
- Model hash propagation to embedding cache
"""

# flake8: noqa: E402
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(
    0,
    str(Path(__file__).parent.parent.parent.parent / "src" / "python"),
)

import numpy as np
from semantic.retrieval import hybrid_retrieve

logger = None  # placeholder, not used in tests


class _MockDAG:
    """Simulates a NetworkX DiGraph with depth attributes.

    Supports ``tag in G`` (``__contains__``) and
    ``G.nodes[tag].get("depth")`` (via dict access).
    """

    def __init__(self, tag_depths: dict[str, int]):
        self._attrs: dict[str, dict] = {
            tag: {"depth": d} for tag, d in tag_depths.items()
        }

    def __contains__(self, tag: object) -> bool:
        return tag in self._attrs

    @property
    def nodes(self) -> dict[str, dict]:
        return self._attrs


class TestHybridRetrieve(unittest.TestCase):
    """Hybrid retrieval tests across exemplar and non-exemplar types."""

    # Shared ontology layout for all tests
    TAG_DEPTHS = {
        "root": 0,
        "root.child": 1,
        "root.child.grandchild": 2,
    }

    def setUp(self):
        # Ontology mocks
        self.mock_get_cached_subtree = mock.patch(
            "semantic.retrieval.candidates.get_cached_subtree",
        ).start()
        self.mock_get_tag_dag = mock.patch(
            "semantic.retrieval.scoring.get_tag_dag",
        ).start()
        self.mock_get_tag_dag.return_value = _MockDAG(
            self.TAG_DEPTHS,
        )

        self.mock_get_scope_for_tag = mock.patch(
            "semantic.retrieval.candidates.get_scope_for_tag",
        ).start()

        # BM25 mock
        self.mock_get_scores = mock.patch(
            "semantic.retrieval.scoring.get_scores",
        ).start()

        # Embedding cache mock
        self.mock_get_embedding = mock.patch(
            "semantic.retrieval.scoring.get_embedding",
        ).start()

        # Exemplar loader mock
        self.mock_load_exemplars = mock.patch(
            "semantic.retrieval.candidates.load_exemplars",
        ).start()

        # DuckDB connection mock
        self.mock_con = mock.MagicMock()

        # Shared test query embedding (L2-normalized)
        self.query_emb = np.array([0.8, 0.6], dtype="float32")

    def tearDown(self):
        mock.patch.stopall()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _setup_exemplar_mocks(
        self,
        exemplar_ids_tag: dict[int, str],
        bm25_scores: dict[int, float],
        emb_scores: dict[int, list[float]],
    ) -> None:
        """Configure exemplar-path mocks with the given data.

        Args:
            exemplar_ids_tag: mapping of exemplar_id -> tag string.
            bm25_scores: mapping of exemplar_id -> BM25 score [0, 1].
            emb_scores: mapping of exemplar_id -> 2-element vector for
                embedding cosine computation.
        """
        # get_cached_subtree
        self.mock_get_cached_subtree.return_value = {
            "tag": "root",
            "ancestors": [],
            "descendants": ["root.child", "root.child.grandchild"],
            "subtree_exemplars": list(exemplar_ids_tag.keys()),
            "subtree_codes": [],
            "subtree_themes": [],
        }

        # load_exemplars
        mock_lazy = mock.MagicMock()
        mock_df = mock.MagicMock()
        mock_lazy.collect.return_value = mock_df
        mock_df.iter_rows.return_value = iter(
            [{"id": eid, "tag": tag} for eid, tag in exemplar_ids_tag.items()],
        )
        self.mock_load_exemplars.return_value = mock_lazy

        # get_scores (BM25)
        self.mock_get_scores.return_value = bm25_scores

        # get_embedding
        def mock_get_emb(con, eid_str, etype, mhash=None):
            eid = int(eid_str)
            vec = emb_scores.get(eid)
            if vec is None:
                return None
            return np.array(vec, dtype="float32")

        self.mock_get_embedding.side_effect = mock_get_emb

    def _setup_code_mocks(
        self,
        db_rows: list[tuple[int, str]],
        scope_tags: set[str],
        emb_scores: dict[int, list[float]],
    ) -> None:
        """Configure code-path mocks with the given data."""
        self.mock_get_scope_for_tag.return_value = scope_tags

        # Nodes table mock
        mock_result = mock.MagicMock()
        mock_result.fetchall.return_value = db_rows
        self.mock_con.execute.return_value = mock_result

        # get_embedding
        def mock_get_emb(con, eid_str, etype, mhash=None):
            eid = int(eid_str)
            vec = emb_scores.get(eid)
            if vec is None:
                return None
            return np.array(vec, dtype="float32")

        self.mock_get_embedding.side_effect = mock_get_emb

    # ------------------------------------------------------------------
    # Exemplar tests
    # ------------------------------------------------------------------

    def test_basic_hybrid_retrieval_exemplars(self):
        """Full pipeline: scope + BM25 + embedding -> ranked results."""
        self._setup_exemplar_mocks(
            exemplar_ids_tag={
                1: "root.child",
                2: "root.child",
                3: "root.child.grandchild",
            },
            bm25_scores={1: 1.0, 2: 0.8, 3: 0.6},
            emb_scores={
                1: [1.0, 0.0],  # dot with query_emb [0.8, 0.6] = 0.8
                2: [0.6, 0.8],  # dot = 0.8*0.6+0.6*0.8 = 0.96
                3: [0.0, 1.0],  # dot = 0.6
            },
        )

        result = hybrid_retrieve(
            query_tag="root",
            query_keywords=["keyword1", "keyword2"],
            query_embedding=self.query_emb,
            candidate_type="exemplar",
            con=self.mock_con,
            k=3,
        )

        # Expected final scores (depth of root=0, root.child=1, grand=2):
        # depth_dist for root.child candidates = |1-0| = 1 -> prox = 0.5
        # depth_dist for grandchild candidate = |2-0| = 2 -> prox = 1/3
        # ID 1: 0.5*0.8 + 0.3*0.5 + 0.2*1.0 = 0.40+0.15+0.20 = 0.75
        # ID 2: 0.5*0.96 + 0.3*0.5 + 0.2*0.8 = 0.48+0.15+0.16 = 0.79
        # ID 3: 0.5*0.6 + 0.3*0.333 + 0.2*0.6 = 0.30+0.10+0.12 = 0.52
        self.assertEqual(len(result), 3)
        self.assertEqual(result[0][0], 2)  # highest: 2
        self.assertEqual(result[1][0], 1)  # second: 1
        self.assertEqual(result[2][0], 3)  # third: 3
        # Verify descending scores
        scores = [s for _, s in result]
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_proximity_boost_favors_same_tag(self):
        """Candidates matching query tag get higher proximity boost."""
        self._setup_exemplar_mocks(
            exemplar_ids_tag={
                1: "root",  # same tag as query -> depth_dist=0
                2: "root.child",  # depth_dist=1
            },
            bm25_scores={1: 0.5, 2: 0.5},
            emb_scores={
                1: [0.5, 0.5],  # dot = 0.8*0.5+0.6*0.5 = 0.70
                2: [0.5, 0.5],  # same
            },
        )

        result = hybrid_retrieve(
            query_tag="root",
            query_keywords=["kw"],
            query_embedding=self.query_emb,
            candidate_type="exemplar",
            con=self.mock_con,
            k=2,
        )

        # Compute manually:
        # ID 1: prox = 1/(1+0) = 1.0
        #   final = 0.5*0.7 + 0.3*1.0 + 0.2*0.5 = 0.35+0.30+0.10 = 0.75
        # ID 2: prox = 1/(1+1) = 0.5
        #   final = 0.5*0.7 + 0.3*0.5 + 0.2*0.5 = 0.35+0.15+0.10 = 0.60
        self.assertEqual(result[0][0], 1)  # same tag ranks higher
        self.assertAlmostEqual(result[0][1], 0.75, places=5)

    def test_tie_breaking_by_entity_id(self):
        """Equal scores resolve by lower entity_id first."""
        self._setup_exemplar_mocks(
            exemplar_ids_tag={
                10: "root.child",
                20: "root.child",
            },
            bm25_scores={10: 0.5, 20: 0.5},
            emb_scores={
                10: [0.5, 0.5],  # dot = 0.70
                20: [0.5, 0.5],  # same
            },
        )

        result = hybrid_retrieve(
            query_tag="root",
            query_keywords=["kw"],
            query_embedding=self.query_emb,
            candidate_type="exemplar",
            con=self.mock_con,
            k=2,
        )

        # Both have same scores, so entity_id=10 should come first
        self.assertEqual(result[0][0], 10)
        self.assertEqual(result[1][0], 20)

    def test_top_k_limit(self):
        """Returns exactly k results when pool >= k."""
        self._setup_exemplar_mocks(
            exemplar_ids_tag={i: "root.child" for i in range(1, 11)},
            bm25_scores={i: i / 10.0 for i in range(1, 11)},
            emb_scores={i: [i / 20.0, 1.0 - i / 20.0] for i in range(1, 11)},
        )

        result = hybrid_retrieve(
            query_tag="root",
            query_keywords=["kw"],
            query_embedding=self.query_emb,
            candidate_type="exemplar",
            con=self.mock_con,
            k=3,
        )

        self.assertEqual(len(result), 3)

    def test_fewer_than_k_candidates(self):
        """Returns all candidates when pool < k."""
        self._setup_exemplar_mocks(
            exemplar_ids_tag={42: "root.child"},
            bm25_scores={42: 0.9},
            emb_scores={42: [0.8, 0.2]},
        )

        result = hybrid_retrieve(
            query_tag="root",
            query_keywords=["kw"],
            query_embedding=self.query_emb,
            candidate_type="exemplar",
            con=self.mock_con,
            k=50,
        )

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0][0], 42)

    def test_empty_candidate_set(self):
        """No candidates in scope returns empty list."""
        self.mock_get_cached_subtree.return_value = {
            "tag": "root",
            "ancestors": [],
            "descendants": [],
            "subtree_exemplars": [],
            "subtree_codes": [],
            "subtree_themes": [],
        }
        mock_lazy = mock.MagicMock()
        mock_df = mock.MagicMock()
        mock_lazy.collect.return_value = mock_df
        mock_df.iter_rows.return_value = iter([])
        self.mock_load_exemplars.return_value = mock_lazy

        result = hybrid_retrieve(
            query_tag="root",
            query_keywords=["kw"],
            query_embedding=self.query_emb,
            candidate_type="exemplar",
            con=self.mock_con,
            k=50,
        )

        self.assertEqual(result, [])

    def test_partial_embedding_cache_miss(self):
        """Some candidates missing from cache are skipped gracefully."""
        self._setup_exemplar_mocks(
            exemplar_ids_tag={
                1: "root.child",
                2: "root.child",
            },
            bm25_scores={1: 0.9, 2: 0.8},
            emb_scores={
                1: [1.0, 0.0],  # present
                # 2 intentionally missing (get_embedding returns None)
            },
        )

        # Override get_embedding: only ID 1 has embedding
        def mock_get_emb(con, eid_str, etype, mhash=None):
            if eid_str == "1":
                return np.array([1.0, 0.0], dtype="float32")
            return None

        self.mock_get_embedding.side_effect = mock_get_emb

        result = hybrid_retrieve(
            query_tag="root",
            query_keywords=["kw"],
            query_embedding=self.query_emb,
            candidate_type="exemplar",
            con=self.mock_con,
            k=50,
        )

        # ID 2 should be in BM25 top but missing from embedding top.
        # Since pool = top_bm25 | top_emb, ID 2 is still in pool.
        # Its emb score defaults to 0.0.
        self.assertEqual(len(result), 2)
        # ID 1: 0.5*0.8 + 0.3*0.5 + 0.2*0.9 = 0.40+0.15+0.18 = 0.73
        # ID 2: 0.5*0.0 + 0.3*0.5 + 0.2*0.8 = 0.00+0.15+0.16 = 0.31
        self.assertEqual(result[0][0], 1)
        self.assertEqual(result[1][0], 2)

    def test_model_hash_propagation(self):
        """model_hash is passed through to get_embedding calls."""
        self._setup_exemplar_mocks(
            exemplar_ids_tag={1: "root.child"},
            bm25_scores={1: 0.5},
            emb_scores={1: [0.5, 0.5]},
        )

        model_hash = "test_hash_123"
        hybrid_retrieve(
            query_tag="root",
            query_keywords=["kw"],
            query_embedding=self.query_emb,
            candidate_type="exemplar",
            con=self.mock_con,
            k=5,
            model_hash=model_hash,
        )

        # Verify get_embedding was called with the hash
        self.mock_get_embedding.assert_called_with(
            self.mock_con,
            "1",
            "exemplar",
            model_hash,
        )

    # ------------------------------------------------------------------
    # Non-exemplar tests
    # ------------------------------------------------------------------

    def test_code_candidate_skips_bm25(self):
        """Code candidates skip BM25 and use renormalized weights."""
        self._setup_code_mocks(
            db_rows=[
                (10, "root.child"),
                (11, "root.child"),
            ],
            scope_tags={"root", "root.child"},
            emb_scores={
                10: [1.0, 0.0],  # dot = 0.8
                11: [0.0, 1.0],  # dot = 0.6
            },
        )

        result = hybrid_retrieve(
            query_tag="root",
            query_keywords=["kw"],
            query_embedding=self.query_emb,
            candidate_type="code",
            con=self.mock_con,
            k=5,
        )

        # BM25 should NOT be called for non-exemplar
        self.mock_get_scores.assert_not_called()

        # depth of root=0, root.child=1 -> depth_dist=1 -> prox=0.5
        # ID 10: 0.625*0.8 + 0.375*0.5 = 0.50 + 0.1875 = 0.6875
        # ID 11: 0.625*0.6 + 0.375*0.5 = 0.375 + 0.1875 = 0.5625
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0][0], 10)
        self.assertAlmostEqual(result[0][1], 0.6875, places=5)

    def test_code_candidate_empty_scope(self):
        """No tags in scope returns empty for non-exemplar types."""
        self.mock_get_scope_for_tag.return_value = set()

        result = hybrid_retrieve(
            query_tag="root",
            query_keywords=["kw"],
            query_embedding=self.query_emb,
            candidate_type="theme",
            con=self.mock_con,
            k=5,
        )

        self.assertEqual(result, [])
        self.mock_get_embedding.assert_not_called()

    def test_non_exemplar_all_at_same_depth(self):
        """All candidates at same depth -> equal proximity boost."""
        self._setup_code_mocks(
            db_rows=[(1, "root.child"), (2, "root.child")],
            scope_tags={"root", "root.child"},
            emb_scores={
                1: [1.0, 0.0],  # dot = 0.8
                2: [0.6, 0.8],  # dot = 0.96
            },
        )

        result = hybrid_retrieve(
            query_tag="root.child",  # depth=1
            query_keywords=["kw"],
            query_embedding=self.query_emb,
            candidate_type="code",
            con=self.mock_con,
            k=5,
        )

        # depth_dist = |1-1| = 0 -> prox = 1.0 for both
        # ID 1: 0.625*0.8 + 0.375*1.0 = 0.50 + 0.375 = 0.875
        # ID 2: 0.625*0.96 + 0.375*1.0 = 0.60 + 0.375 = 0.975
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0][0], 2)  # higher emb score ranks first
        self.assertEqual(result[1][0], 1)

    def test_non_exemplar_con_execute_called(self):
        """Verifies con.execute is called for non-exemplar resolution."""
        self._setup_code_mocks(
            db_rows=[(1, "root.child")],
            scope_tags={"root", "root.child"},
            emb_scores={1: [0.5, 0.5]},
        )

        hybrid_retrieve(
            query_tag="root",
            query_keywords=["kw"],
            query_embedding=self.query_emb,
            candidate_type="code",
            con=self.mock_con,
            k=5,
        )

        self.mock_con.execute.assert_called_once()


if __name__ == "__main__":
    unittest.main()
