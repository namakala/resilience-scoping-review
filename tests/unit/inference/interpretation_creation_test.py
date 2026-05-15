"""Integration tests for inference/interpretation_creation.py.

Uses a real DuckDB database with initialized graph schema,
creating interpretation nodes and verifying edges, status, contiguity,
and error handling.
"""

# flake8: noqa: E402
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(
    0, str(Path(__file__).parent.parent.parent.parent / "src" / "python")
)  # noqa: E402

import duckdb  # noqa: E402
import networkx as nx  # noqa: E402
from graph import (  # noqa: E402
    get_interpretations_by_span_tag,
    get_node,
    get_nodes_by_type_and_tag,
)
from graph.exceptions import ForeignKeyError  # noqa: E402
from graph.node_crud import create_node as _real_create_node  # noqa: E402
from inference.inference_status_crud import init_inference_status_table  # noqa: E402
from inference.inference_status_queries import get_status  # noqa: E402
from inference.inference_status_types import (  # noqa: E402
    ENTITY_INTERPRETATION,
    GENERATED,
    STAGE_INTERPRETATION,
)
from inference.interpretation_creation import create_interpretation_nodes
from inference.parsing import InterpretationInference
from persistence.duckdb_init import initialize_database


def _build_tag_dag() -> nx.DiGraph:
    """Build a minimal ontology DAG for test use.

    Hierarchy::

        Root
         +-- T1
         +-- T2
         |    +-- T2.A
         +-- T3
    """
    G = nx.DiGraph()
    tags = [
        ("Root", 0),
        ("T1", 1),
        ("T2", 1),
        ("T2.A", 2),
        ("T3", 1),
    ]
    for tag, depth in tags:
        G.add_node(tag, depth=depth)
    G.add_edge("Root", "T1")
    G.add_edge("Root", "T2")
    G.add_edge("T2", "T2.A")
    G.add_edge("Root", "T3")
    return G


class TestCreateInterpretationNodes(unittest.TestCase):
    """Integration tests for create_interpretation_nodes()."""

    def setUp(self) -> None:
        self.tmpdir = Path(tempfile.mkdtemp())
        self.db_path = self.tmpdir / "test_session.duckdb"
        initialize_database(db_path=self.db_path)
        self.con = duckdb.connect(str(self.db_path))
        init_inference_status_table(self.con)
        import graph.singleton as singleton

        singleton._graph = None

        self.tag_dag = _build_tag_dag()
        self._dag_patcher = patch("ontology.dag.get_tag_dag", return_value=self.tag_dag)
        self._dag_patcher.start()

    def tearDown(self) -> None:
        self._dag_patcher.stop()
        self.con.close()
        import shutil

        shutil.rmtree(self.tmpdir)
        import graph.singleton as singleton

        singleton._graph = None

    def _precreate_theme_nodes(self, tag_map: dict[str, str]) -> dict[str, int]:
        """Create prerequisite theme nodes; return {theme_name: node_id}.

        Args:
            tag_map: {theme_name: tag} mapping e.g. {"Th1": "T1", "Th2": "T2"}
        """
        ids: dict[str, int] = {}
        for name, tag in tag_map.items():
            nid = _real_create_node(
                node_type="theme",
                name=name,
                definition=f"Narrative for {name}",
                tag=tag,
                status="approved",
                data_json={"code_ids": ["1"]},
                db_path=self.db_path,
            )
            ids[name] = nid
        return ids

    def _make_interpretation_item(
        self,
        name: str,
        theme_ids: list[str],
        narrative: str = "Cross-cutting narrative",
        key_insights: list[str] | None = None,
    ) -> InterpretationInference:
        return InterpretationInference(
            interpretation_name=name,
            narrative=narrative,
            theme_ids=theme_ids,
            key_insights=key_insights or ["insight 1"],
        )

    # ── Basic creation ────────────────────────────────────────────────────

    def test_single_interpretation_creates_node_and_spans_edges(self):
        """One interpretation creates one node + N spans edges + tag_spans."""
        theme_map = self._precreate_theme_nodes({"Th1": "T1", "Th2": "T2"})
        interps = [
            self._make_interpretation_item(
                "CrossCut1",
                [str(theme_map["Th1"]), str(theme_map["Th2"])],
            )
        ]
        node_ids = create_interpretation_nodes(self.con, interps, db_path=self.db_path)
        self.assertEqual(len(node_ids), 1)

        nid = node_ids[0]
        node = get_node(nid, db_path=self.db_path)
        self.assertEqual(node["type"], "interpretation")
        self.assertEqual(node["name"], "CrossCut1")
        self.assertEqual(node["definition"], "Cross-cutting narrative")
        self.assertEqual(node["status"], "draft")
        self.assertIsInstance(node["data_json"], dict)
        tag_spans = node["data_json"]["tag_spans"]
        self.assertSetEqual(set(tag_spans), {"T1", "T2"})
        # Root tag is the one with minimum depth (Root=0, T1=1, T2=1 → T1)
        self.assertEqual(node["tag"], "T1")

        # Verify spans edges
        spans_edges = self.con.execute(
            "SELECT source_id, target_id, edge_type FROM edges WHERE edge_type = 'spans'"
        ).fetchall()
        self.assertEqual(len(spans_edges), 2)
        for src, tgt, etype in spans_edges:
            self.assertEqual(src, nid)
            self.assertEqual(etype, "spans")
            self.assertIn(tgt, {theme_map["Th1"], theme_map["Th2"]})

    def test_multiple_interpretations(self):
        """Two interpretations → two nodes + edges."""
        theme_map = self._precreate_theme_nodes({"Th1": "T1", "Th2": "T2", "Th3": "T3"})
        interps = [
            self._make_interpretation_item(
                "I1", [str(theme_map["Th1"]), str(theme_map["Th2"])]
            ),
            self._make_interpretation_item(
                "I2", [str(theme_map["Th2"]), str(theme_map["Th3"])]
            ),
        ]
        node_ids = create_interpretation_nodes(self.con, interps, db_path=self.db_path)
        self.assertEqual(len(node_ids), 2)

        nodes = [get_node(nid, db_path=self.db_path) for nid in node_ids]
        names = {n["name"] for n in nodes}
        self.assertSetEqual(names, {"I1", "I2"})

    # ── Edge cases ────────────────────────────────────────────────────────

    def test_empty_interpretations_returns_empty(self):
        result = create_interpretation_nodes(self.con, [], db_path=self.db_path)
        self.assertEqual(result, [])

    def test_empty_name_raises(self):
        interps = [
            InterpretationInference(
                interpretation_name="",
                narrative="n",
                theme_ids=["1"],
                key_insights=["k"],
            )
        ]
        with self.assertRaises(ValueError):
            create_interpretation_nodes(self.con, interps, db_path=self.db_path)

    def test_missing_theme_id_raises_keyerror(self):
        """Non-existent theme_id causes KeyError + transaction rollback."""
        interps = [self._make_interpretation_item("I1", ["999999"])]
        with self.assertRaises(KeyError):
            create_interpretation_nodes(self.con, interps, db_path=self.db_path)
        nodes = self.con.execute(
            "SELECT COUNT(*) FROM nodes WHERE type = 'interpretation'"
        ).fetchone()
        self.assertEqual(nodes[0], 0)

    def test_missing_theme_id_raises_foreignkey_if_theme_arg(self):
        """Missing theme IDs referenced after tag resolution fails."""
        theme_map = self._precreate_theme_nodes({"Th1": "T1"})
        interps = [
            self._make_interpretation_item("I1", [str(theme_map["Th1"]), "999999"])
        ]
        with self.assertRaises(KeyError):
            create_interpretation_nodes(self.con, interps, db_path=self.db_path)

    # ── Inference status ──────────────────────────────────────────────────

    def test_inference_status_set_to_generated(self):
        theme_map = self._precreate_theme_nodes({"Th1": "T1", "Th2": "T2"})
        interps = [
            self._make_interpretation_item(
                "I1", [str(theme_map["Th1"]), str(theme_map["Th2"])]
            )
        ]
        node_ids = create_interpretation_nodes(self.con, interps, db_path=self.db_path)
        status = get_status(
            self.con, str(node_ids[0]), ENTITY_INTERPRETATION, STAGE_INTERPRETATION
        )
        self.assertIsNotNone(status)
        self.assertEqual(status["status"], GENERATED)

    def test_multiple_nodes_all_have_status(self):
        theme_map = self._precreate_theme_nodes({"Th1": "T1", "Th2": "T2", "Th3": "T3"})
        interps = [
            self._make_interpretation_item(
                "I1", [str(theme_map["Th1"]), str(theme_map["Th2"])]
            ),
            self._make_interpretation_item(
                "I2", [str(theme_map["Th2"]), str(theme_map["Th3"])]
            ),
        ]
        node_ids = create_interpretation_nodes(self.con, interps, db_path=self.db_path)
        for nid in node_ids:
            status = get_status(
                self.con, str(nid), ENTITY_INTERPRETATION, STAGE_INTERPRETATION
            )
            self.assertIsNotNone(status)
            self.assertEqual(status["status"], GENERATED)

    # ── Non-contiguous tag_spans ──────────────────────────────────────────

    def test_non_contiguous_tag_spans_raises(self):
        """Tags forming disconnected branches (missing LCA path) fail."""
        theme_map = self._precreate_theme_nodes({"ThA": "T1", "ThC": "T2.A"})
        # T1 and T2.A: path from LCA Root is Root→T2→T2.A, missing T2
        interps = [
            self._make_interpretation_item(
                "Bad", [str(theme_map["ThA"]), str(theme_map["ThC"])]
            )
        ]
        with self.assertRaises(ValueError) as ctx:
            create_interpretation_nodes(self.con, interps, db_path=self.db_path)
        self.assertIn("non-contiguous", str(ctx.exception))

    def test_single_tag_span_is_valid(self):
        """A single theme tag is trivially contiguous."""
        theme_map = self._precreate_theme_nodes({"Th1": "T1"})
        interps = [self._make_interpretation_item("Single", [str(theme_map["Th1"])])]
        node_ids = create_interpretation_nodes(self.con, interps, db_path=self.db_path)
        self.assertEqual(len(node_ids), 1)
        node = get_node(node_ids[0], db_path=self.db_path)
        self.assertEqual(node["data_json"]["tag_spans"], ["T1"])

    # ── Queryability by tag_spans ────────────────────────────────────────

    def test_nodes_queryable_by_span_tag(self):
        """get_interpretations_by_span_tag returns by any tag in tag_spans."""
        theme_map = self._precreate_theme_nodes({"Th1": "T1", "Th2": "T2"})
        interps = [
            self._make_interpretation_item(
                "Q1", [str(theme_map["Th1"]), str(theme_map["Th2"])]
            )
        ]
        create_interpretation_nodes(self.con, interps, db_path=self.db_path)

        results = get_interpretations_by_span_tag("T1", db_path=self.db_path)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["name"], "Q1")

        results_t2 = get_interpretations_by_span_tag("T2", db_path=self.db_path)
        self.assertEqual(len(results_t2), 1)

    def test_queryable_by_root_tag(self):
        """get_nodes_by_type_and_tag('interpretation', root_tag) works."""
        theme_map = self._precreate_theme_nodes({"Th1": "T1", "Th2": "T2"})
        interps = [
            self._make_interpretation_item(
                "RootQ", [str(theme_map["Th1"]), str(theme_map["Th2"])]
            )
        ]
        create_interpretation_nodes(self.con, interps, db_path=self.db_path)

        # Root tag for {"T1", "T2"} is "T1" (minimum depth)
        nodes = get_nodes_by_type_and_tag("interpretation", "T1", db_path=self.db_path)
        self.assertEqual(len(nodes), 1)
        self.assertEqual(nodes[0]["name"], "RootQ")

    # ── Evidence chain traversal ──────────────────────────────────────────

    def test_evidence_chain_traceable(self):
        """Traverse: interpretation → theme → codes via graph."""
        # Create code nodes and theme nodes
        code_id = _real_create_node(
            node_type="code",
            name="Code1",
            definition="A test code",
            tag="T1",
            status="approved",
            db_path=self.db_path,
        )
        theme_id = _real_create_node(
            node_type="theme",
            name="Th1",
            definition="Theme narrative",
            tag="T1",
            status="approved",
            data_json={"code_ids": [str(code_id)]},
            db_path=self.db_path,
        )
        # Create edge: theme composed-of code
        self.con.execute(
            "INSERT INTO edges (source_id, target_id, edge_type) VALUES (?, ?, 'composed-of')",
            [theme_id, code_id],
        )

        # Create interpretation over the theme
        interps = [self._make_interpretation_item("EvidenceChain", [str(theme_id)])]
        node_ids = create_interpretation_nodes(self.con, interps, db_path=self.db_path)
        interp_id = node_ids[0]

        # Verify interpretation → theme edge
        spans_row = self.con.execute(
            "SELECT source_id, target_id, edge_type FROM edges "
            "WHERE edge_type = 'spans' AND source_id = ?",
            [interp_id],
        ).fetchone()
        self.assertIsNotNone(spans_row)
        self.assertEqual(spans_row[1], theme_id)

        # Verify theme → code edge
        composed_row = self.con.execute(
            "SELECT source_id, target_id, edge_type FROM edges "
            "WHERE edge_type = 'composed-of' AND source_id = ?",
            [theme_id],
        ).fetchone()
        self.assertIsNotNone(composed_row)
        self.assertEqual(composed_row[1], code_id)

        # Full traversal: interpretation → theme → code is traceable
        interp_node = get_node(interp_id, db_path=self.db_path)
        theme_node = get_node(theme_id, db_path=self.db_path)
        code_node = get_node(code_id, db_path=self.db_path)
        self.assertEqual(interp_node["type"], "interpretation")
        self.assertEqual(theme_node["type"], "theme")
        self.assertEqual(code_node["type"], "code")

    # ── Derived-from re-synthesis chain ─────────────────────────────────

    def test_derived_from_chain_on_re_synthesis(self):
        """Re-synthesis creates derived-from edge old→new."""
        theme_map = self._precreate_theme_nodes({"Th1": "T1", "Th2": "T2", "Th3": "T3"})
        interps1 = [
            self._make_interpretation_item(
                "Synth",
                [str(theme_map["Th1"]), str(theme_map["Th2"])],
                narrative="v1",
            )
        ]
        ids1 = create_interpretation_nodes(self.con, interps1, db_path=self.db_path)

        interps2 = [
            self._make_interpretation_item(
                "Synth",
                [str(theme_map["Th2"]), str(theme_map["Th3"])],
                narrative="v2",
            )
        ]
        ids2 = create_interpretation_nodes(self.con, interps2, db_path=self.db_path)

        # Old node was renamed
        old_node = get_node(ids1[0], db_path=self.db_path)
        self.assertIn("_deprecated_", old_node["name"])

        # New node has canonical name
        new_node = get_node(ids2[0], db_path=self.db_path)
        self.assertEqual(new_node["name"], "Synth")

        # Verify derived-from edge: old → new
        edges = self.con.execute(
            "SELECT source_id, target_id, edge_type FROM edges "
            "WHERE edge_type = 'derived-from'"
        ).fetchall()
        self.assertEqual(len(edges), 1)
        self.assertEqual(edges[0][0], ids1[0])
        self.assertEqual(edges[0][1], ids2[0])

    def test_derived_from_chain_multiple_re_syntheses(self):
        """Three synthesis runs: v1→v2 and v2→v3."""
        theme_map = self._precreate_theme_nodes({"Th1": "T1", "Th2": "T2", "Th3": "T3"})
        ids = []
        for version in range(3):
            interps = [
                self._make_interpretation_item(
                    "X",
                    [str(theme_map["Th1"])],
                    narrative=f"version {version}",
                )
            ]
            ids.append(
                create_interpretation_nodes(self.con, interps, db_path=self.db_path)[0]
            )

        edges = self.con.execute(
            "SELECT source_id, target_id, edge_type FROM edges "
            "WHERE edge_type = 'derived-from' ORDER BY source_id"
        ).fetchall()
        self.assertEqual(len(edges), 2)
        self.assertEqual(edges[0][0], ids[0])
        self.assertEqual(edges[0][1], ids[1])
        self.assertEqual(edges[1][0], ids[1])
        self.assertEqual(edges[1][1], ids[2])

    # ── Transactional rollback ──────────────────────────────────────────

    def test_transactional_rollback_on_error(self):
        """If an error occurs inside graph_transaction, nothing is committed."""
        theme_map = self._precreate_theme_nodes({"Th1": "T1", "Th2": "T2"})
        interps = [
            self._make_interpretation_item("Good", [str(theme_map["Th1"])]),
            self._make_interpretation_item("Bad", [str(theme_map["Th2"])]),
        ]
        call_count = [0]

        def _side_effect(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] >= 2:
                raise ValueError("Simulated failure inside transaction")
            return _real_create_node(*args, **kwargs)

        with patch(
            "inference.interpretation_creation.create_node",
            side_effect=_side_effect,
        ):
            with self.assertRaises(ValueError):
                create_interpretation_nodes(self.con, interps, db_path=self.db_path)

        # No interpretation nodes should remain in the DB
        interp_nodes = self.con.execute(
            "SELECT COUNT(*) FROM nodes WHERE type = 'interpretation'"
        ).fetchone()[0]
        self.assertEqual(interp_nodes, 0)

        # No spans edges
        edges = self.con.execute(
            "SELECT COUNT(*) FROM edges WHERE edge_type = 'spans'"
        ).fetchone()[0]
        self.assertEqual(edges, 0)

    def test_transactional_rollback_on_re_synthesis(self):
        """Error during re-synthesis rolls back both rename and creation."""
        theme_map = self._precreate_theme_nodes({"Th1": "T1", "Th2": "T2", "Th3": "T3"})

        # First synthesis: create interpretation "Rollback"
        ids1 = create_interpretation_nodes(
            self.con,
            [
                self._make_interpretation_item(
                    "Rollback",
                    [str(theme_map["Th1"]), str(theme_map["Th2"])],
                )
            ],
            db_path=self.db_path,
        )

        # Re-synthesis with error
        interps = [
            self._make_interpretation_item(
                "Rollback",
                [str(theme_map["Th2"]), str(theme_map["Th3"])],
            )
        ]

        def _side_effect(*args, **kwargs):
            raise ValueError("Simulated failure on create_node")

        with patch(
            "inference.interpretation_creation.create_node",
            side_effect=_side_effect,
        ):
            with self.assertRaises(ValueError):
                create_interpretation_nodes(self.con, interps, db_path=self.db_path)

        # Old interpretation should still exist with original name
        old_node = get_node(ids1[0], db_path=self.db_path)
        self.assertEqual(old_node["name"], "Rollback")
        self.assertEqual(old_node["status"], "draft")

        # No new interpretation node was created
        all_interps = self.con.execute(
            "SELECT COUNT(*) FROM nodes WHERE type = 'interpretation'"
        ).fetchone()[0]
        self.assertEqual(all_interps, 1)

        # No derived-from edge
        edges = self.con.execute(
            "SELECT COUNT(*) FROM edges WHERE edge_type = 'derived-from'"
        ).fetchone()[0]
        self.assertEqual(edges, 0)

    # ── Name dedup within batch ──────────────────────────────────────────

    def test_duplicate_names_within_batch(self):
        """Two interpretations with same name both created (one suffixed)."""
        theme_map = self._precreate_theme_nodes({"Th1": "T1", "Th2": "T2", "Th3": "T3"})
        interps = [
            self._make_interpretation_item("Dup", [str(theme_map["Th1"])]),
            self._make_interpretation_item(
                "Dup", [str(theme_map["Th2"]), str(theme_map["Th3"])]
            ),
        ]
        node_ids = create_interpretation_nodes(self.con, interps, db_path=self.db_path)
        self.assertEqual(len(node_ids), 2)

        nodes = [get_node(nid, db_path=self.db_path) for nid in node_ids]
        names = {n["name"] for n in nodes}
        self.assertIn("Dup", names)
        self.assertIn("Dup_1", names)

    # ── Tag spans with empty set ─────────────────────────────────────────

    def test_interpretation_with_no_theme_tags(self):
        """Themes with empty tag fields result in empty tag_spans."""
        theme_id = _real_create_node(
            node_type="theme",
            name="TaglessTheme",
            definition="No tag",
            tag="",
            status="approved",
            db_path=self.db_path,
        )
        interps = [self._make_interpretation_item("Tagless", [str(theme_id)])]
        node_ids = create_interpretation_nodes(self.con, interps, db_path=self.db_path)
        self.assertEqual(len(node_ids), 1)
        node = get_node(node_ids[0], db_path=self.db_path)
        self.assertEqual(node["data_json"]["tag_spans"], [])


if __name__ == "__main__":
    unittest.main()
