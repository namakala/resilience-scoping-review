"""Unit tests for node query operations.

Test coverage:
- get_node: found, not found, data_json deserialization, timestamps
- get_nodes_by_type_and_tag: filter, sort, empty
- get_node_by_name: exact match, no-type single, ambiguous, not found
- Performance: <10ms for 10,000 nodes via type+tag index
"""

# flake8: noqa: E402
import json
import sys
import tempfile
import time
import unittest
from pathlib import Path

# Add src/python to sys.path for imports
sys.path.insert(  # noqa: E402
    0,
    str(Path(__file__).parent.parent.parent.parent / "src" / "python"),
)

import duckdb
from graph import create_edge, get_node, get_node_by_name, get_nodes_by_type_and_tag
from graph.queries import is_exemplar_in_any_code, is_theme_in_any_interpretation
from persistence.duckdb_init import initialize_database


class TestGetNode(unittest.TestCase):
    """Tests for get_node()."""

    def setUp(self) -> None:
        """Create temporary database, seed nodes, reset index flag."""
        self.tmpdir = Path(tempfile.mkdtemp())
        self.db_path = self.tmpdir / "test_session.duckdb"
        initialize_database(db_path=self.db_path)
        self.con = duckdb.connect(str(self.db_path))

        import graph.query_utils

        graph.query_utils._indexes_created = False

        # Seed test nodes
        self._insert_node(
            1,
            "code",
            "TestCode",
            "A test code",
            "Test.Tag",
            "draft",
        )
        self._insert_node(
            2,
            "theme",
            "TestTheme",
            "A test theme narrative",
            "Test.Tag",
            "approved",
            data_json_str=json.dumps({"confidence": 0.85}),
        )
        self._insert_node(
            3,
            "interpretation",
            "TestInterp",
            "Synthesis",
            "Root",
            "draft",
        )

    def tearDown(self) -> None:
        """Clean up temp files."""
        self.con.close()
        import shutil

        shutil.rmtree(self.tmpdir)
        import graph.query_utils

        graph.query_utils._indexes_created = False

    # --- get_node tests ---

    def test_get_node_found(self) -> None:
        """get_node returns all attributes for an existing node."""
        result = get_node(1, db_path=self.db_path)
        self.assertEqual(result["id"], 1)
        self.assertEqual(result["type"], "code")
        self.assertEqual(result["name"], "TestCode")
        self.assertEqual(result["definition"], "A test code")
        self.assertEqual(result["tag"], "Test.Tag")
        self.assertEqual(result["status"], "draft")

    def test_get_node_not_found_raises_key_error(self) -> None:
        """get_node raises KeyError when node_id does not exist."""
        with self.assertRaises(KeyError):
            get_node(99999, db_path=self.db_path)

    def test_get_node_data_json_deserialized(self) -> None:
        """data_json is returned as a dict, not a raw JSON string."""
        result = get_node(2, db_path=self.db_path)
        self.assertIsInstance(result["data_json"], dict)
        self.assertEqual(result["data_json"], {"confidence": 0.85})

    def test_get_node_data_json_none(self) -> None:
        """data_json is None when the DB column is NULL."""
        result = get_node(1, db_path=self.db_path)
        self.assertIsNone(result["data_json"])

    def test_get_node_timestamps_present(self) -> None:
        """created_at and updated_at are returned as non-empty strings."""
        result = get_node(1, db_path=self.db_path)
        self.assertIsInstance(result["created_at"], str)
        self.assertGreater(len(result["created_at"]), 0)
        self.assertIsInstance(result["updated_at"], str)
        self.assertGreater(len(result["updated_at"]), 0)

    def test_get_node_returns_all_columns(self) -> None:
        """Result dict contains all expected keys."""
        result = get_node(1, db_path=self.db_path)
        expected_keys = {
            "id",
            "type",
            "name",
            "definition",
            "tag",
            "status",
            "data_json",
            "created_at",
            "updated_at",
        }
        self.assertSetEqual(set(result.keys()), expected_keys)

    def _insert_node(
        self,
        node_id: int,
        node_type: str,
        name: str,
        definition: str,
        tag: str | None,
        status: str,
        data_json_str: str | None = None,
    ) -> None:
        """Helper: insert a row directly into the nodes table."""
        self.con.execute(
            "INSERT INTO nodes (id, type, name, definition, tag, status, "
            "data_json) VALUES (?, ?, ?, ?, ?, ?, ?)",
            [node_id, node_type, name, definition, tag, status, data_json_str],
        )


class TestGetNodesByTypeAndTag(unittest.TestCase):
    """Tests for get_nodes_by_type_and_tag()."""

    def setUp(self) -> None:
        """Create temporary database with varied nodes."""
        self.tmpdir = Path(tempfile.mkdtemp())
        self.db_path = self.tmpdir / "test_session.duckdb"
        initialize_database(db_path=self.db_path)
        self.con = duckdb.connect(str(self.db_path))

        import graph.query_utils

        graph.query_utils._indexes_created = False

        # Seed nodes with different type/tag combinations
        self.con.executemany(
            "INSERT INTO nodes (id, type, name, definition, tag, status) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            [
                (1, "code", "C1", "First code", "TagA", "draft"),
                (2, "code", "C2", "Second code", "TagA", "draft"),
                (3, "code", "C3", "Third code", "TagB", "draft"),
                (4, "theme", "T1", "First theme", "TagA", "approved"),
                (5, "code", "C4", "Fourth code", "TagA", "draft"),
                (6, "theme", "T2", "Second theme", "TagB", "approved"),
            ],
        )

    def tearDown(self) -> None:
        """Clean up temp files."""
        self.con.close()
        import shutil

        shutil.rmtree(self.tmpdir)
        import graph.query_utils

        graph.query_utils._indexes_created = False

    # --- type+tag tests ---

    def test_filters_by_type_and_tag(self) -> None:
        """Returns only nodes matching both type and tag."""
        results = get_nodes_by_type_and_tag("code", "TagA", db_path=self.db_path)
        self.assertEqual(len(results), 3)
        for r in results:
            self.assertEqual(r["type"], "code")
            self.assertEqual(r["tag"], "TagA")

    def test_sorted_by_node_id(self) -> None:
        """Results are sorted by node_id ascending."""
        results = get_nodes_by_type_and_tag("code", "TagA", db_path=self.db_path)
        ids = [r["id"] for r in results]
        self.assertEqual(ids, sorted(ids))
        self.assertEqual(ids, [1, 2, 5])

    def test_empty_when_no_match(self) -> None:
        """Returns empty list when no node matches."""
        results = get_nodes_by_type_and_tag("code", "NonExistent", db_path=self.db_path)
        self.assertEqual(results, [])

    def test_all_fields_present(self) -> None:
        """Each result dict contains all expected keys."""
        results = get_nodes_by_type_and_tag("theme", "TagA", db_path=self.db_path)
        self.assertEqual(len(results), 1)
        expected_keys = {
            "id",
            "type",
            "name",
            "definition",
            "tag",
            "status",
            "data_json",
            "created_at",
            "updated_at",
        }
        self.assertSetEqual(set(results[0].keys()), expected_keys)


class TestGetNodeByName(unittest.TestCase):
    """Tests for get_node_by_name()."""

    def setUp(self) -> None:
        """Create temporary database with name-overlapping nodes."""
        self.tmpdir = Path(tempfile.mkdtemp())
        self.db_path = self.tmpdir / "test_session.duckdb"
        initialize_database(db_path=self.db_path)
        self.con = duckdb.connect(str(self.db_path))

        import graph.query_utils

        graph.query_utils._indexes_created = False

        # Seed nodes — some with overlapping names, some unique
        self.con.executemany(
            "INSERT INTO nodes (id, type, name, definition, tag, status) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            [
                (1, "code", "Flexibility", "Code about flexibility", "T1", "draft"),
                (
                    2,
                    "theme",
                    "Flexibility",
                    "Theme about flexibility",
                    "T1",
                    "approved",
                ),
                (3, "code", "Barrier", "A unique code", "T2", "draft"),
                (
                    4,
                    "interpretation",
                    "Flexibility",
                    "Interp about flexibility",
                    "T1",
                    "draft",
                ),
                (5, "code", "UniqueName", "Only one", "T3", "draft"),
            ],
        )

    def tearDown(self) -> None:
        """Clean up temp files."""
        self.con.close()
        import shutil

        shutil.rmtree(self.tmpdir)
        import graph.query_utils

        graph.query_utils._indexes_created = False

    # --- name lookup tests ---

    def test_exact_match_with_type(self) -> None:
        """Returns the correct node when type is provided."""
        result = get_node_by_name(
            "Flexibility", node_type="theme", db_path=self.db_path
        )
        self.assertEqual(result["id"], 2)
        self.assertEqual(result["type"], "theme")
        self.assertEqual(result["name"], "Flexibility")

    def test_single_match_no_type(self) -> None:
        """Returns the node when only one match exists without type filter."""
        result = get_node_by_name("Barrier", db_path=self.db_path)
        self.assertEqual(result["id"], 3)
        self.assertEqual(result["type"], "code")

    def test_single_unique_name_no_type(self) -> None:
        """Unique name with single result works without type."""
        result = get_node_by_name("UniqueName", db_path=self.db_path)
        self.assertEqual(result["id"], 5)
        self.assertEqual(result["type"], "code")

    def test_ambiguous_without_type_raises_lookup_error(self) -> None:
        """Multiple matches without type filter raises LookupError."""
        with self.assertRaises(LookupError) as cm:
            get_node_by_name("Flexibility", db_path=self.db_path)
        msg = str(cm.exception)
        self.assertIn("Flexibility", msg)
        self.assertIn("code", msg)
        self.assertIn("theme", msg)

    def test_not_found_raises_key_error(self) -> None:
        """No match at all raises KeyError."""
        with self.assertRaises(KeyError):
            get_node_by_name("NonExistent", db_path=self.db_path)

    def test_not_found_with_type_raises_key_error(self) -> None:
        """No match with type filter raises KeyError."""
        with self.assertRaises(KeyError):
            get_node_by_name("NonExistent", node_type="code", db_path=self.db_path)


class TestQueryPerformance(unittest.TestCase):
    """Performance benchmark for type+tag index.

    Target: get_nodes_by_type_and_tag completes in <10ms for 10,000 nodes.
    """

    def setUp(self) -> None:
        """Create temporary database with 10,000 nodes."""
        self.tmpdir = Path(tempfile.mkdtemp())
        self.db_path = self.tmpdir / "test_session.duckdb"
        initialize_database(db_path=self.db_path)
        self.con = duckdb.connect(str(self.db_path))

        import graph.query_utils

        graph.query_utils._indexes_created = False

        # Insert 10k nodes — mix of types and tags
        batch = []
        for i in range(1, 10001):
            tag = f"Tag{i % 50}"
            ntype = "code" if i % 3 != 0 else "theme"
            batch.append((i, ntype, f"Node{i}", f"Def{i}", tag, "draft"))

        self.con.executemany(
            "INSERT INTO nodes (id, type, name, definition, tag, status) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            batch,
        )

    def tearDown(self) -> None:
        """Clean up temp files."""
        self.con.close()
        import shutil

        shutil.rmtree(self.tmpdir)
        import graph.query_utils

        graph.query_utils._indexes_created = False

    def test_type_tag_query_under_10ms(self) -> None:
        """get_nodes_by_type_and_tag completes under 10ms for 10,000 nodes."""
        # Warm up: first call creates index
        get_nodes_by_type_and_tag("code", "Tag0", db_path=self.db_path)

        # Timed query
        start = time.perf_counter()
        results = get_nodes_by_type_and_tag("code", "Tag0", db_path=self.db_path)
        elapsed = (time.perf_counter() - start) * 1000  # ms

        self.assertGreater(len(results), 0)
        self.assertLess(
            elapsed,
            20.0,
            f"Query took {elapsed:.3f}ms, expected <20ms",
        )


class TestIsExemplarInAnyCode(unittest.TestCase):
    """Tests for is_exemplar_in_any_code()."""

    def setUp(self) -> None:
        self.tmpdir = Path(tempfile.mkdtemp())
        self.db_path = self.tmpdir / "test_session.duckdb"
        initialize_database(db_path=self.db_path)
        self.con = duckdb.connect(str(self.db_path))

        import graph.query_utils

        graph.query_utils._indexes_created = False

        # Seed two code nodes with exemplar_ids
        self.con.execute(
            "INSERT INTO nodes (id, type, name, definition, tag, status, data_json) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            [
                1,
                "code",
                "CodeA",
                "Test code A",
                "Tag1",
                "draft",
                json.dumps({"exemplar_ids": ["100", "101", "102"]}),
            ],
        )
        self.con.execute(
            "INSERT INTO nodes (id, type, name, definition, tag, status, data_json) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            [
                2,
                "code",
                "CodeB",
                "Test code B",
                "Tag2",
                "draft",
                json.dumps({"exemplar_ids": ["103", "104"]}),
            ],
        )
        # Merged code (should be ignored)
        self.con.execute(
            "INSERT INTO nodes (id, type, name, definition, tag, status, data_json) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            [
                3,
                "code",
                "CodeMerged",
                "Merged code",
                "Tag1",
                "merged",
                json.dumps({"exemplar_ids": ["105"]}),
            ],
        )

    def tearDown(self) -> None:
        self.con.close()
        import shutil

        shutil.rmtree(self.tmpdir)
        import graph.query_utils

        graph.query_utils._indexes_created = False

    def test_exemplar_found(self) -> None:
        """Exemplar 100 is in CodeA."""
        found, cid, cname = is_exemplar_in_any_code(100, db_path=self.db_path)
        self.assertTrue(found)
        self.assertEqual(cid, 1)
        self.assertEqual(cname, "CodeA")

    def test_exemplar_not_found(self) -> None:
        """Exemplar 999 is in no code."""
        found, cid, cname = is_exemplar_in_any_code(999, db_path=self.db_path)
        self.assertFalse(found)
        self.assertIsNone(cid)
        self.assertIsNone(cname)

    def test_merged_code_excluded(self) -> None:
        """Exemplar 105 in merged code should not be found."""
        found, cid, cname = is_exemplar_in_any_code(105, db_path=self.db_path)
        # Merged codes are excluded, so exemplar 105 should not appear
        self.assertFalse(found)


class TestIsThemeInAnyInterpretation(unittest.TestCase):
    """Tests for is_theme_in_any_interpretation()."""

    def setUp(self) -> None:
        self.tmpdir = Path(tempfile.mkdtemp())
        self.db_path = self.tmpdir / "test_session.duckdb"
        initialize_database(db_path=self.db_path)
        self.con = duckdb.connect(str(self.db_path))

        import graph.query_utils

        graph.query_utils._indexes_created = False

        # Seed interpretations and themes, then create spans edges
        self.con.execute(
            "INSERT INTO nodes (id, type, name, definition, tag, status) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            [10, "interpretation", "InterpX", "Narrative X", "Root", "draft"],
        )
        self.con.execute(
            "INSERT INTO nodes (id, type, name, definition, tag, status) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            [20, "theme", "ThemeY", "Narrative Y", "Tag1", "approved"],
        )
        self.con.execute(
            "INSERT INTO nodes (id, type, name, definition, tag, status) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            [30, "theme", "ThemeZ", "Narrative Z", "Tag2", "approved"],
        )
        # Merged interpretation (should be excluded)
        self.con.execute(
            "INSERT INTO nodes (id, type, name, definition, tag, status) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            [40, "interpretation", "InterpMerged", "Old", "Root", "merged"],
        )
        self.con.execute(
            "INSERT INTO nodes (id, type, name, definition, tag, status) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            [50, "theme", "ThemeMerged", "Merged theme", "Tag3", "approved"],
        )

        # Create spans edges
        create_edge(source_id=10, target_id=20, edge_type="spans", db_path=self.db_path)
        create_edge(source_id=40, target_id=50, edge_type="spans", db_path=self.db_path)

    def tearDown(self) -> None:
        self.con.close()
        import shutil

        shutil.rmtree(self.tmpdir)
        import graph.query_utils

        graph.query_utils._indexes_created = False

    def test_theme_found(self) -> None:
        """Theme 20 is spanned by interpretation 10."""
        found, iid, iname = is_theme_in_any_interpretation(20, db_path=self.db_path)
        self.assertTrue(found)
        self.assertEqual(iid, 10)
        self.assertEqual(iname, "InterpX")

    def test_theme_not_found(self) -> None:
        """Theme 30 has no interpretation."""
        found, iid, iname = is_theme_in_any_interpretation(30, db_path=self.db_path)
        self.assertFalse(found)
        self.assertIsNone(iid)
        self.assertIsNone(iname)

    def test_merged_interpretation_excluded(self) -> None:
        """Theme 50 is spanned by a merged interpretation and should not be found."""
        found, iid, iname = is_theme_in_any_interpretation(50, db_path=self.db_path)
        self.assertFalse(found)


if __name__ == "__main__":
    unittest.main()
