"""Unit tests for compute_inputs_hash.

Covers:
- Deterministic hashing: same inputs → same hash
- Sensitivity: different inputs → different hash
- Type normalizers: dict, list, None, polars LazyFrame/DataFrame,
  networkx DiGraph, numpy ndarray, dataclasses, fallback
- Empty / edge-case inputs
"""

# flake8: noqa: E402
import sys
import unittest
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(
    0,
    str(Path(__file__).parent.parent.parent.parent / "src" / "python"),
)

import hashlib

import networkx as nx
import numpy as np
import polars as pl
from pipeline.caching import compute_inputs_hash


class TestComputeInputsHash(unittest.TestCase):
    """Tests for compute_inputs_hash."""

    # ── Determinism ──────────────────────────────────────────────────

    def test_deterministic_same_inputs(self) -> None:
        """Same inputs produce the same hash."""
        inputs = {"a": 1, "b": "hello", "c": [1, 2, 3]}
        h1 = compute_inputs_hash(inputs)
        h2 = compute_inputs_hash(inputs)
        self.assertEqual(h1, h2)

    def test_deterministic_key_order_irrelevant(self) -> None:
        """Hash is invariant to dict key ordering."""
        inputs_a = {"x": 10, "y": 20}
        inputs_b = {"y": 20, "x": 10}
        self.assertEqual(
            compute_inputs_hash(inputs_a),
            compute_inputs_hash(inputs_b),
        )

    # ── Sensitivity ──────────────────────────────────────────────────

    def test_different_inputs_different_hash(self) -> None:
        """Changing a value changes the hash."""
        base = {"value": 42}
        changed = {"value": 43}
        self.assertNotEqual(
            compute_inputs_hash(base),
            compute_inputs_hash(changed),
        )

    def test_different_keys_different_hash(self) -> None:
        """Adding a key changes the hash."""
        h1 = compute_inputs_hash({"a": 1})
        h2 = compute_inputs_hash({"a": 1, "b": 2})
        self.assertNotEqual(h1, h2)

    # ── Nested dicts ─────────────────────────────────────────────────

    def test_nested_dicts(self) -> None:
        """Nested dicts normalize correctly."""
        inputs = {"outer": {"inner": [1, 2], "key": "val"}}
        h = compute_inputs_hash(inputs)
        assert h is not None
        self.assertEqual(64, len(h))

    def test_nested_dict_key_order_irrelevant(self) -> None:
        """Nested dict key order does not affect the hash."""
        a = {"cfg": {"z": 1, "a": 2}}
        b = {"cfg": {"a": 2, "z": 1}}
        self.assertEqual(
            compute_inputs_hash(a),
            compute_inputs_hash(b),
        )

    # ── None / booleans ──────────────────────────────────────────────

    def test_none_value(self) -> None:
        """None is handled correctly."""
        h = compute_inputs_hash({"key": None})
        self.assertIsNotNone(h)

    def test_booleans(self) -> None:
        """True/False are hashed deterministically."""
        self.assertIsNotNone(compute_inputs_hash({"flag": True}))
        self.assertIsNotNone(compute_inputs_hash({"flag": False}))

    # ── Lists and tuples ─────────────────────────────────────────────

    def test_list_value(self) -> None:
        """Lists are normalized correctly."""
        inputs = {"items": [3, 1, 2]}
        h = compute_inputs_hash(inputs)
        self.assertIsNotNone(h)

    def test_tuple_value(self) -> None:
        """Tuples are normalized correctly (as lists)."""
        inputs = {"coords": (10, 20)}
        h = compute_inputs_hash(inputs)
        self.assertIsNotNone(h)

    # ── Polars LazyFrame ─────────────────────────────────────────────

    def test_lazyframe_schema(self) -> None:
        """LazyFrame input is normalized to its schema."""
        lf = pl.LazyFrame({"x": [1, 2], "y": ["a", "b"]})
        h = compute_inputs_hash({"data": lf})
        self.assertIsNotNone(h)

    def test_lazyframe_deterministic(self) -> None:
        """Same schema → same hash."""
        lf1 = pl.LazyFrame({"col": [1]})
        lf2 = pl.LazyFrame({"col": [2]})
        # Same schema regardless of data
        self.assertEqual(
            compute_inputs_hash({"data": lf1}),
            compute_inputs_hash({"data": lf2}),
        )

    def test_lazyframe_different_schema_different_hash(self) -> None:
        """Different column sets → different hash."""
        lf1 = pl.LazyFrame({"a": [1]})
        lf2 = pl.LazyFrame({"a": [1], "b": [2]})
        self.assertNotEqual(
            compute_inputs_hash({"data": lf1}),
            compute_inputs_hash({"data": lf2}),
        )

    # ── Polars DataFrame ─────────────────────────────────────────────

    def test_dataframe_normalized(self) -> None:
        """DataFrame is normalized with schema + height."""
        df = pl.DataFrame({"x": [1, 2, 3]})
        h = compute_inputs_hash({"df": df})
        self.assertIsNotNone(h)

    def test_dataframe_height_affects_hash(self) -> None:
        """Different row counts → different hash."""
        df1 = pl.DataFrame({"x": [1]})
        df2 = pl.DataFrame({"x": [1, 2]})
        self.assertNotEqual(
            compute_inputs_hash({"df": df1}),
            compute_inputs_hash({"df": df2}),
        )

    # ── NetworkX DiGraph ─────────────────────────────────────────────

    def test_digraph_normalized(self) -> None:
        """DiGraph is normalized via node_link_data."""
        G = nx.DiGraph()
        G.add_node("root", depth=0)
        G.add_edge("root", "child")
        h = compute_inputs_hash({"graph": G})
        self.assertIsNotNone(h)

    def test_digraph_deterministic(self) -> None:
        """Same graph → same hash."""
        G1 = nx.DiGraph([("a", "b")])
        G2 = nx.DiGraph([("a", "b")])
        self.assertEqual(
            compute_inputs_hash({"g": G1}),
            compute_inputs_hash({"g": G2}),
        )

    def test_digraph_different_structure_different_hash(self) -> None:
        """Different graph edges change the hash."""
        G1 = nx.DiGraph([("a", "b")])
        G2 = nx.DiGraph([("a", "c")])
        self.assertNotEqual(
            compute_inputs_hash({"g": G1}),
            compute_inputs_hash({"g": G2}),
        )

    # ── NumPy ndarray ────────────────────────────────────────────────

    def test_ndarray_normalized(self) -> None:
        """NumPy array is normalized via tolist."""
        arr = np.array([[1.0, 2.0], [3.0, 4.0]], dtype=np.float32)
        h = compute_inputs_hash({"embeddings": arr})
        self.assertIsNotNone(h)

    def test_ndarray_shape_sensitivity(self) -> None:
        """Different shape → different hash."""
        a1 = np.array([1, 2, 3], dtype=np.int32)
        a2 = np.array([[1, 2], [3, 4]], dtype=np.int32)
        self.assertNotEqual(
            compute_inputs_hash({"arr": a1}),
            compute_inputs_hash({"arr": a2}),
        )

    def test_ndarray_values_sensitivity(self) -> None:
        """Different values → different hash."""
        a1 = np.array([1.0, 2.0], dtype=np.float32)
        a2 = np.array([1.0, 99.0], dtype=np.float32)
        self.assertNotEqual(
            compute_inputs_hash({"arr": a1}),
            compute_inputs_hash({"arr": a2}),
        )

    # ── Dataclasses ──────────────────────────────────────────────────

    def test_dataclass_normalized(self) -> None:
        """Dataclass fields are extracted via asdict."""

        @dataclass
        class Cfg:
            batch_size: int = 64
            model: str = "bert"

        h = compute_inputs_hash({"config": Cfg()})
        self.assertIsNotNone(h)

    def test_dataclass_different_values_different_hash(self) -> None:
        """Changing a dataclass field changes the hash."""

        @dataclass
        class Cfg:
            n: int

        h1 = compute_inputs_hash({"cfg": Cfg(10)})
        h2 = compute_inputs_hash({"cfg": Cfg(20)})
        self.assertNotEqual(h1, h2)

    # ── Edge cases ───────────────────────────────────────────────────

    def test_empty_dict(self) -> None:
        """Empty inputs produce a valid hash."""
        h = compute_inputs_hash({})
        assert h is not None
        self.assertEqual(64, len(h))

    def test_many_entries_stable(self) -> None:
        """Large inputs are handled deterministically."""
        inputs = {f"key_{i}": i for i in range(100)}
        h1 = compute_inputs_hash(inputs)
        h2 = compute_inputs_hash(inputs)
        self.assertEqual(h1, h2)

    def test_mixed_types(self) -> None:
        """A mix of different types normalizes to a stable hash."""
        G = nx.DiGraph()
        G.add_edge("a", "b")
        inputs = {
            "name": "test",
            "batch_size": 32,
            "flags": [True, False],
            "graph": G,
        }
        h = compute_inputs_hash(inputs)
        self.assertIsNotNone(h)
        # Verify deterministic
        self.assertEqual(h, compute_inputs_hash(inputs))

    # ── string encoding ──────────────────────────────────────────────

    def test_unicode_handling(self) -> None:
        """Unicode strings produce deterministic hashes."""
        inputs = {"text": "café résumé 日本語"}
        h = compute_inputs_hash(inputs)
        self.assertIsNotNone(h)
        # Same unicode inputs → same hash
        self.assertEqual(
            h,
            compute_inputs_hash({"text": "café résumé 日本語"}),
        )

    # ── Hash format ──────────────────────────────────────────────────

    def test_hash_format(self) -> None:
        """Hash is a 64-character hex string."""
        h = compute_inputs_hash({"a": 1})
        assert h is not None
        self.assertRegex(h, r"^[0-9a-f]{64}$")


if __name__ == "__main__":
    unittest.main()
