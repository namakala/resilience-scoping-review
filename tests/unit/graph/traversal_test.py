"""Unit tests for graph traversal operations.

Test coverage:
- get_children: immediate 1-hop successors
- get_parents: immediate 1-hop predecessors
- get_successors: all descendants (transitive closure)
- get_predecessors: all ancestors (transitive closure)
- get_path: shortest directed path between nodes
- Cycle detection raises CycleError
- Edge direction respected (DiGraph)
- Error propagation for nonexistent nodes
- Performance: depth-5 path under 1ms
"""

# flake8: noqa: E402
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
import networkx as nx
from graph import (
    CycleError,
    clear_traversal_cache,
    get_children,
    get_graph,
    get_parents,
    get_path,
    get_predecessors,
    get_successors,
    rebuild_graph,
)
from persistence.duckdb_connection import get_connection
from persistence.duckdb_init import initialize_database


class TestTraversal(unittest.TestCase):
    """Tests for graph traversal functions.

    Test tree structure (parent-child edges):
    ::

        1
        |-- 2
        |   |-- 4
        |   +-- 5
        |-- 3
        |   +-- 6
        |
        disconnected: 7 (no edges)
    """

    def setUp(self) -> None:
        """Create temporary database with traversal test tree."""
        self.tmpdir = Path(tempfile.mkdtemp())
        self.db_path = self.tmpdir / "test_session.duckdb"
        initialize_database(db_path=self.db_path)
        self.con = duckdb.connect(str(self.db_path))
        import graph.singleton as singleton

        singleton._graph = None
        clear_traversal_cache()

        self._seed_tree()

    def tearDown(self) -> None:
        """Clean up temp files and reset singleton."""
        self.con.close()
        import shutil

        shutil.rmtree(self.tmpdir)
        import graph.singleton as singleton

        singleton._graph = None
        clear_traversal_cache()

    def _insert_nodes(self, nodes: list[tuple]) -> None:
        """Helper: insert node tuples (id, type, name, definition, tag, status)."""
        for node in nodes:
            self.con.execute(
                """
                INSERT INTO nodes (id, type, name, definition, tag, status)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                node,
            )

    def _insert_edges(self, edges: list[tuple]) -> None:
        """Helper: insert edge tuples (source_id, target_id, edge_type, metadata_json)."""
        for edge in edges:
            self.con.execute(
                """
                INSERT INTO edges (source_id, target_id, edge_type, metadata_json)
                VALUES (?, ?, ?, ?)
                """,
                edge,
            )

    def _seed_tree(self) -> None:
        """Insert the standard test tree into DuckDB."""
        self._insert_nodes(
            [
                (1, "tag", "Root", "Root tag", None, "immutable"),
                (2, "tag", "ChildA", "First child", None, "immutable"),
                (3, "tag", "ChildB", "Second child", None, "immutable"),
                (4, "code", "LeafA", "Leaf under ChildA", "TagA", "draft"),
                (5, "tag", "LeafB", "Leaf under ChildA", None, "immutable"),
                (6, "code", "LeafC", "Leaf under ChildB", "TagB", "draft"),
                (7, "tag", "Disconnected", "No edges", None, "immutable"),
            ]
        )
        self._insert_edges(
            [
                (1, 2, "parent-child", None),
                (1, 3, "parent-child", None),
                (2, 4, "parent-child", None),
                (2, 5, "parent-child", None),
                (3, 6, "parent-child", None),
            ]
        )
        # Build the in-memory graph from DuckDB
        get_graph(db_path=self.db_path)

    # --- get_children ---

    def test_get_children_root(self) -> None:
        """Root node returns both direct children."""
        children = get_children(1, db_path=self.db_path)
        self.assertEqual(children, [2, 3])

    def test_get_children_intermediate(self) -> None:
        """Intermediate node returns its direct children."""
        children = get_children(2, db_path=self.db_path)
        self.assertEqual(children, [4, 5])

    def test_get_children_leaf(self) -> None:
        """Leaf node returns empty list."""
        children = get_children(4, db_path=self.db_path)
        self.assertEqual(children, [])

    def test_get_children_disconnected(self) -> None:
        """Disconnected node (no edges) returns empty list."""
        children = get_children(7, db_path=self.db_path)
        self.assertEqual(children, [])

    def test_get_children_ordered(self) -> None:
        """Children are returned in sorted order by node ID."""
        children = get_children(1, db_path=self.db_path)
        self.assertEqual(children, sorted(children))

    # --- get_parents ---

    def test_get_parents_leaf(self) -> None:
        """Leaf node returns its single parent."""
        parents = get_parents(4, db_path=self.db_path)
        self.assertEqual(parents, [2])

    def test_get_parents_intermediate(self) -> None:
        """Intermediate node returns its parent."""
        parents = get_parents(2, db_path=self.db_path)
        self.assertEqual(parents, [1])

    def test_get_parents_root(self) -> None:
        """Root node returns empty list."""
        parents = get_parents(1, db_path=self.db_path)
        self.assertEqual(parents, [])

    def test_get_parents_disconnected(self) -> None:
        """Disconnected node (no edges) returns empty list."""
        parents = get_parents(7, db_path=self.db_path)
        self.assertEqual(parents, [])

    def test_get_parents_ordered(self) -> None:
        """Parents are returned in sorted order."""
        # Add a second parent to node 4
        self._insert_nodes([(8, "tag", "ExtraParent", None, None, "immutable")])
        self.con.execute(
            "INSERT INTO edges (source_id, target_id, edge_type) VALUES (?, ?, ?)",
            [8, 4, "parent-child"],
        )
        rebuild_graph(db_path=self.db_path)
        parents = get_parents(4, db_path=self.db_path)
        self.assertEqual(parents, sorted(parents))

    # --- get_successors ---

    def test_get_successors_root(self) -> None:
        """Root returns all descendants (entire tree except self)."""
        descendants = get_successors(1, db_path=self.db_path)
        self.assertEqual(set(descendants), {2, 3, 4, 5, 6})

    def test_get_successors_intermediate(self) -> None:
        """Intermediate node returns descendants in its subtree."""
        descendants = get_successors(2, db_path=self.db_path)
        self.assertEqual(set(descendants), {4, 5})

    def test_get_successors_leaf(self) -> None:
        """Leaf node has no descendants."""
        descendants = get_successors(4, db_path=self.db_path)
        self.assertEqual(descendants, [])

    def test_get_successors_disconnected(self) -> None:
        """Disconnected node has no descendants."""
        descendants = get_successors(7, db_path=self.db_path)
        self.assertEqual(descendants, [])

    def test_get_successors_ordered(self) -> None:
        """Descendants are returned in sorted order."""
        descendants = get_successors(1, db_path=self.db_path)
        self.assertEqual(descendants, sorted(descendants))

    # --- get_predecessors ---

    def test_get_predecessors_deep_leaf(self) -> None:
        """Deep leaf returns all ancestors up to root."""
        ancestors = get_predecessors(6, db_path=self.db_path)
        self.assertEqual(set(ancestors), {1, 3})

    def test_get_predecessors_intermediate(self) -> None:
        """Intermediate node returns its path to root."""
        ancestors = get_predecessors(2, db_path=self.db_path)
        self.assertEqual(set(ancestors), {1})

    def test_get_predecessors_root(self) -> None:
        """Root node has no ancestors."""
        ancestors = get_predecessors(1, db_path=self.db_path)
        self.assertEqual(ancestors, [])

    def test_get_predecessors_disconnected(self) -> None:
        """Disconnected node has no ancestors."""
        ancestors = get_predecessors(7, db_path=self.db_path)
        self.assertEqual(ancestors, [])

    def test_get_predecessors_ordered(self) -> None:
        """Ancestors are returned in sorted order."""
        ancestors = get_predecessors(6, db_path=self.db_path)
        self.assertEqual(ancestors, sorted(ancestors))

    # --- get_path ---

    def test_get_path_root_to_leaf(self) -> None:
        """Path from root to deep leaf traverses intermediate nodes."""
        path = get_path(1, 6, db_path=self.db_path)
        self.assertEqual(path, [1, 3, 6])

    def test_get_path_siblings(self) -> None:
        """No directed path between siblings (edges are parent->child only)."""
        path = get_path(4, 5, db_path=self.db_path)
        self.assertIsNone(path)

    def test_get_path_same_node(self) -> None:
        """Path from a node to itself returns single-element list."""
        path = get_path(3, 3, db_path=self.db_path)
        self.assertEqual(path, [3])

    def test_get_path_none_when_disconnected(self) -> None:
        """No path between disconnected nodes returns None."""
        path = get_path(4, 7, db_path=self.db_path)
        self.assertIsNone(path)

    def test_get_path_none_reverse_direction(self) -> None:
        """No path from leaf to root (wrong direction) returns None."""
        path = get_path(6, 1, db_path=self.db_path)
        self.assertIsNone(path)

    # --- get_path: nonexistent nodes ---

    def test_get_path_nonexistent_source(self) -> None:
        """Nonexistent source node raises NodeNotFound."""
        with self.assertRaises(nx.NodeNotFound):
            get_path(999, 1, db_path=self.db_path)

    def test_get_path_nonexistent_target(self) -> None:
        """Nonexistent target node raises NodeNotFound."""
        with self.assertRaises(nx.NodeNotFound):
            get_path(1, 999, db_path=self.db_path)

    # --- cycle detection ---

    def test_cycle_detected_in_get_successors(self) -> None:
        """Cycle in graph raises CycleError in get_successors."""
        # Add edge creating cycle: 3 -> 1 (reverse parent-child)
        self._insert_edges([(3, 1, "parent-child", None)])
        rebuild_graph(db_path=self.db_path)
        with self.assertRaises(CycleError):
            get_successors(1, db_path=self.db_path)

    def test_cycle_detected_in_get_predecessors(self) -> None:
        """Cycle in graph raises CycleError in get_predecessors."""
        self._insert_edges([(6, 3, "parent-child", None)])
        rebuild_graph(db_path=self.db_path)
        with self.assertRaises(CycleError):
            get_predecessors(3, db_path=self.db_path)

    def test_cycle_detected_in_get_path(self) -> None:
        """Cycle in graph raises CycleError in get_path."""
        self._insert_edges([(3, 1, "parent-child", None)])
        rebuild_graph(db_path=self.db_path)
        with self.assertRaises(CycleError):
            get_path(1, 6, db_path=self.db_path)

    def test_no_cycle_error_for_immediate_children(self) -> None:
        """get_children works even when graph has a cycle."""
        self._insert_edges([(3, 1, "parent-child", None)])
        rebuild_graph(db_path=self.db_path)
        children = get_children(1, db_path=self.db_path)
        self.assertEqual(children, [2, 3])

    def test_no_cycle_error_for_immediate_parents(self) -> None:
        """get_parents works even when graph has a cycle (1-hop only)."""
        self._insert_edges([(3, 1, "parent-child", None)])
        rebuild_graph(db_path=self.db_path)
        # Node 1 now has predecessor 3 (the cyclic edge) — no CycleError
        parents = get_parents(1, db_path=self.db_path)
        self.assertEqual(parents, [3])

    # --- edge direction ---

    def test_edge_direction_get_children(self) -> None:
        """Children follow outgoing edges source->target."""
        children = get_children(1, db_path=self.db_path)
        self.assertIn(2, children)
        self.assertNotIn(1, get_children(2, db_path=self.db_path))

    def test_edge_direction_get_parents(self) -> None:
        """Parents follow incoming edges target<-source."""
        parents = get_parents(4, db_path=self.db_path)
        self.assertIn(2, parents)
        self.assertNotIn(4, get_parents(1, db_path=self.db_path))

    def test_edge_direction_reverse_not_mutual(self) -> None:
        """Reverse direction does not return the original node."""
        self.assertNotIn(
            1,
            get_children(2, db_path=self.db_path),
        )
        self.assertNotIn(
            2,
            get_parents(1, db_path=self.db_path),
        )

    # --- nonexistent nodes ---

    def test_get_children_nonexistent(self) -> None:
        """Nonexistent node raises NetworkXError in get_children."""
        with self.assertRaises(nx.NetworkXError):
            get_children(999, db_path=self.db_path)

    def test_get_parents_nonexistent(self) -> None:
        """Nonexistent node raises NetworkXError in get_parents."""
        with self.assertRaises(nx.NetworkXError):
            get_parents(999, db_path=self.db_path)

    def test_get_successors_nonexistent(self) -> None:
        """Nonexistent node raises NetworkXError."""
        with self.assertRaises(nx.NetworkXError):
            get_successors(999, db_path=self.db_path)

    def test_get_predecessors_nonexistent(self) -> None:
        """Nonexistent node raises NetworkXError."""
        with self.assertRaises(nx.NetworkXError):
            get_predecessors(999, db_path=self.db_path)

    # --- cache management ---

    def test_get_children_cached_same_result(self) -> None:
        """Repeated calls return the same cached result."""
        r1 = get_children(1, db_path=self.db_path)
        r2 = get_children(1, db_path=self.db_path)
        self.assertEqual(r1, r2)

    def test_clear_cache_reflects_new_data(self) -> None:
        """After clearing cache, fresh data is loaded."""
        _ = get_children(2, db_path=self.db_path)
        clear_traversal_cache()
        # Add a new child to node 2
        self._insert_nodes(
            [(9, "code", "NewChild", "Added after cache", "TagA", "draft")]
        )
        self._insert_edges([(2, 9, "parent-child", None)])
        rebuild_graph(db_path=self.db_path)
        children = get_children(2, db_path=self.db_path)
        self.assertIn(9, children)

    # --- performance ---

    def test_performance_depth5_path(self) -> None:
        """Path between depth-5 nodes completes in <1ms."""
        # Create a chain: 10->11->12->13->14->15 (depth 5)
        self._insert_nodes(
            [
                (10, "tag", "Depth0", None, None, "immutable"),
                (11, "tag", "Depth1", None, None, "immutable"),
                (12, "tag", "Depth2", None, None, "immutable"),
                (13, "tag", "Depth3", None, None, "immutable"),
                (14, "tag", "Depth4", None, None, "immutable"),
                (15, "tag", "Depth5", None, None, "immutable"),
            ]
        )
        self._insert_edges(
            [
                (10, 11, "parent-child", None),
                (11, 12, "parent-child", None),
                (12, 13, "parent-child", None),
                (13, 14, "parent-child", None),
                (14, 15, "parent-child", None),
            ]
        )
        # Rebuild graph with chain
        rebuild_graph(db_path=self.db_path)

        start = time.perf_counter()
        path = get_path(10, 15, db_path=self.db_path)
        elapsed = time.perf_counter() - start

        self.assertEqual(path, [10, 11, 12, 13, 14, 15])
        self.assertLess(
            elapsed,
            0.001,
            f"get_path took {elapsed * 1000:.2f}ms, expected <1ms",
        )


if __name__ == "__main__":
    unittest.main()
