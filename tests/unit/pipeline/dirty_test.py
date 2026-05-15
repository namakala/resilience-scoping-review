"""Tests for pipeline/dirty.py — dirty flag propagation, clearing, and checking."""

# flake8: noqa: E402
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "src" / "python"))

import duckdb
from persistence.state_repository import load_state, save_state
from persistence.state_updates import get_dirty_flags
from pipeline.dirty import (
    any_tag_dirty,
    clear_all_dirty,
    clear_dirty,
    is_dirty,
    propagate_dirty,
    set_dirty,
)


def _make_con():
    """Create an in-memory DuckDB connection with the session_state table."""
    con = duckdb.connect(":memory:")
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS session_state (
            key VARCHAR PRIMARY KEY,
            value VARCHAR NOT NULL,
            type VARCHAR NOT NULL
        );
        """
    )
    return con


# ── set_dirty ───────────────────────────────────────────────────────


class TestSetDirty:
    def test_set_dirty_sets_flag_true(self):
        con = _make_con()
        try:
            set_dirty(con, "Tag.A")
            flags = get_dirty_flags(con)
            assert flags.get("Tag.A") is True
        finally:
            con.close()

    def test_set_dirty_creates_row_if_missing(self):
        con = _make_con()
        try:
            set_dirty(con, "NewTag")
            state = load_state(con)
            assert state["dirty_flags"] == {"NewTag": True}
        finally:
            con.close()

    def test_set_dirty_preserves_existing_flags(self):
        con = _make_con()
        try:
            state = {
                "current_stage": 5,
                "dirty_flags": {"Tag.A": True, "Tag.B": False},
                "last_checkpoint": None,
                "config_version": "",
                "user_action_count": 0,
            }
            save_state(con, state)
            set_dirty(con, "Tag.C")
            flags = get_dirty_flags(con)
            assert flags == {"Tag.A": True, "Tag.B": False, "Tag.C": True}
        finally:
            con.close()


# ── propagate_dirty ─────────────────────────────────────────────────


class TestPropagateDirty:
    def test_propagate_dirty_sets_tag_and_ancestors(self):
        """propagate_dirty marks the tag + its ontology ancestors dirty."""
        import networkx as nx
        import ontology.dag as od

        con = _make_con()
        try:
            # Build a minimal ontology DAG and inject into the singleton
            G = nx.DiGraph()
            G.add_node("Problem", depth=0)
            G.add_node("Problem.Cause", depth=1)
            G.add_node("Problem.Cause.Detail", depth=2)
            G.add_edge("Problem", "Problem.Cause")
            G.add_edge("Problem.Cause", "Problem.Cause.Detail")
            od._ONTOLOGY_GRAPH = G
            from ontology.traversal import clear_traversal_cache

            clear_traversal_cache()

            propagate_dirty(con, "Problem.Cause.Detail")
            flags = get_dirty_flags(con)
            assert flags.get("Problem.Cause.Detail") is True
            assert flags.get("Problem.Cause") is True
            assert flags.get("Problem") is True
        finally:
            con.close()
            od._ONTOLOGY_GRAPH = None
            from ontology.traversal import clear_traversal_cache

            clear_traversal_cache()

    def test_propagate_dirty_with_ontology_dag(self):
        """When ontology DAG is loaded, ancestors are also marked dirty."""
        import networkx as nx
        import ontology.dag as od

        con = _make_con()
        try:
            G = nx.DiGraph()
            G.add_node("Problem", depth=0)
            G.add_node("Problem.Cause", depth=1)
            G.add_node("Problem.Cause.Detail", depth=2)
            G.add_edge("Problem", "Problem.Cause")
            G.add_edge("Problem.Cause", "Problem.Cause.Detail")
            od._ONTOLOGY_GRAPH = G
            from ontology.traversal import clear_traversal_cache

            clear_traversal_cache()

            propagate_dirty(con, "Problem.Cause.Detail")
            flags = get_dirty_flags(con)
            assert flags.get("Problem.Cause.Detail") is True
            assert flags.get("Problem.Cause") is True
            assert flags.get("Problem") is True
        finally:
            con.close()
            od._ONTOLOGY_GRAPH = None
            from ontology.traversal import clear_traversal_cache

            clear_traversal_cache()

    def test_propagate_dirty_unknown_tag(self):
        """Unknown tag sets bare flag without ancestors (no KeyError crash)."""
        import networkx as nx
        import ontology.dag as od

        con = _make_con()
        try:
            # Set an empty DAG so get_ancestors raises KeyError
            od._ONTOLOGY_GRAPH = nx.DiGraph()
            from ontology.traversal import clear_traversal_cache

            clear_traversal_cache()

            propagate_dirty(con, "Fake.Tag.XYZ")
            flags = get_dirty_flags(con)
            assert flags.get("Fake.Tag.XYZ") is True
        finally:
            con.close()
            od._ONTOLOGY_GRAPH = None
            from ontology.traversal import clear_traversal_cache

            clear_traversal_cache()

    def test_propagate_dirty_marks_upward_not_sideways(self):
        """Ancestors are dirty, but sibling tags are not."""
        import networkx as nx
        import ontology.dag as od

        con = _make_con()
        try:
            G = nx.DiGraph()
            G.add_node("Root", depth=0)
            G.add_node("Root.A", depth=1)
            G.add_node("Root.B", depth=1)
            G.add_edge("Root", "Root.A")
            G.add_edge("Root", "Root.B")
            od._ONTOLOGY_GRAPH = G
            from ontology.traversal import clear_traversal_cache

            clear_traversal_cache()

            propagate_dirty(con, "Root.A")
            flags = get_dirty_flags(con)
            assert flags.get("Root.A") is True
            assert flags.get("Root") is True
            assert flags.get("Root.B", False) is False
        finally:
            con.close()
            od._ONTOLOGY_GRAPH = None
            from ontology.traversal import clear_traversal_cache

            clear_traversal_cache()


# ── clear_dirty ─────────────────────────────────────────────────────


class TestClearDirty:
    def test_clear_dirty_sets_flag_false(self):
        con = _make_con()
        try:
            from persistence.state_updates import update_dirty_flag

            update_dirty_flag(con, "Tag.A", True)
            clear_dirty(con, "Tag.A")
            flags = get_dirty_flags(con)
            assert flags.get("Tag.A") is False
        finally:
            con.close()

    def test_clear_dirty_preserves_other_flags(self):
        con = _make_con()
        try:
            from persistence.state_updates import update_dirty_flag

            update_dirty_flag(con, "Tag.A", True)
            update_dirty_flag(con, "Tag.B", True)
            clear_dirty(con, "Tag.A")
            flags = get_dirty_flags(con)
            assert flags.get("Tag.A") is False
            assert flags.get("Tag.B") is True
        finally:
            con.close()


# ── clear_all_dirty ─────────────────────────────────────────────────


class TestClearAllDirty:
    def test_clear_all_dirty_empties_flags(self):
        con = _make_con()
        try:
            from persistence.state_updates import update_dirty_flag

            update_dirty_flag(con, "Tag.A", True)
            update_dirty_flag(con, "Tag.B", True)
            clear_all_dirty(con)
            flags = get_dirty_flags(con)
            assert flags == {}
        finally:
            con.close()

    def test_clear_all_dirty_preserves_other_state(self):
        con = _make_con()
        try:
            state = {
                "current_stage": 7,
                "dirty_flags": {"Tag.A": True},
                "last_checkpoint": None,
                "config_version": "v1",
                "user_action_count": 10,
            }
            save_state(con, state)
            clear_all_dirty(con)
            loaded = load_state(con)
            assert loaded["current_stage"] == 7
            assert loaded["dirty_flags"] == {}
        finally:
            con.close()


# ── is_dirty (pure function) ────────────────────────────────────────


class TestIsDirty:
    def test_is_dirty_returns_true_when_dirty(self):
        assert is_dirty("Tag.A", {"Tag.A": True}) is True

    def test_is_dirty_returns_false_when_clean(self):
        assert is_dirty("Tag.A", {"Tag.A": False}) is False

    def test_is_dirty_returns_false_when_absent(self):
        assert is_dirty("Tag.A", {}) is False

    def test_is_dirty_returns_false_on_empty_dict(self):
        assert is_dirty("Tag.A", {}) is False

    def test_is_dirty_with_mixed_flags(self):
        flags = {"Tag.A": True, "Tag.B": False, "Tag.C": True}
        assert is_dirty("Tag.A", flags) is True
        assert is_dirty("Tag.B", flags) is False
        assert is_dirty("Tag.C", flags) is True
        assert is_dirty("Tag.D", flags) is False


# ── any_tag_dirty (pure function) ───────────────────────────────────


class TestAnyTagDirty:
    def test_any_tag_dirty_true_when_one_dirty(self):
        assert (
            any_tag_dirty(["Tag.A", "Tag.B"], {"Tag.A": False, "Tag.B": True}) is True
        )

    def test_any_tag_dirty_false_when_all_clean(self):
        assert (
            any_tag_dirty(["Tag.A", "Tag.B"], {"Tag.A": False, "Tag.B": False}) is False
        )

    def test_any_tag_dirty_false_when_none_present(self):
        assert any_tag_dirty(["Tag.A"], {}) is False

    def test_any_tag_dirty_empty_tags_list(self):
        assert any_tag_dirty([], {"Tag.A": True}) is False

    def test_any_tag_dirty_empty_flags(self):
        assert any_tag_dirty(["Tag.A"], {}) is False
