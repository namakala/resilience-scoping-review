"""Tests for inference/batching.py — batch grouping by tag."""

# flake8: noqa: E402
import sys
import unittest
from pathlib import Path
from typing import cast

sys.path.insert(
    0, str(Path(__file__).parent.parent.parent.parent / "src" / "python")
)  # noqa: E402

from inference.batching import (  # noqa: E402
    Batch,
    BatchableItem,
    _chunk_list,
    group_by_similarity,
    group_by_tag,
)

# ── helpers ─────────────────────────────────────────────────────────────────


def _make_item(tag: str, item_id: int | str) -> BatchableItem:
    """Create a simple object satisfying the BatchableItem protocol."""
    return cast(BatchableItem, type("Item", (), {"tag": tag, "id": item_id})())


# ── chunk_list (internal helper) ─────────────────────────────────────────────


class TestChunkList(unittest.TestCase):
    """Internal list-chunking utility."""

    def test_exact_division(self):
        chunks = _chunk_list([1, 2, 3, 4], 2)
        self.assertEqual(chunks, [[1, 2], [3, 4]])

    def test_remainder(self):
        chunks = _chunk_list([1, 2, 3, 4, 5], 2)
        self.assertEqual(chunks, [[1, 2], [3, 4], [5]])

    def test_single_chunk(self):
        chunks = _chunk_list([1, 2, 3], 5)
        self.assertEqual(chunks, [[1, 2, 3]])

    def test_empty_list(self):
        chunks = _chunk_list([], 3)
        self.assertEqual(chunks, [])

    def test_chunk_size_one(self):
        chunks = _chunk_list([1, 2, 3], 1)
        self.assertEqual(chunks, [[1], [2], [3]])


# ── batch_id property ────────────────────────────────────────────────────────


class TestBatchId(unittest.TestCase):
    """Batch.batch_id computed property."""

    def test_default_prefix(self):
        b = Batch(tag="Problem.Cause", items=[], batch_index=0, total_batches=1)
        b._prefix = "tag"
        self.assertEqual(b.batch_id, "tag_Problem.Cause_batch_00")

    def test_custom_prefix(self):
        b = Batch(tag="Solution", items=[], batch_index=2, total_batches=3)
        b._prefix = "code"
        self.assertEqual(b.batch_id, "code_Solution_batch_02")

    def test_two_digit_format(self):
        b = Batch(tag="Root", items=[], batch_index=10, total_batches=15)
        b._prefix = "tag"
        self.assertEqual(b.batch_id, "tag_Root_batch_10")

    def test_tags_with_dots_preserved(self):
        b = Batch(
            tag="Problem.Scope.Association",
            items=[],
            batch_index=0,
            total_batches=1,
        )
        b._prefix = "tag"
        self.assertEqual(b.batch_id, "tag_Problem.Scope.Association_batch_00")


# ── group_by_tag ─────────────────────────────────────────────────────────────


class TestGroupByTag(unittest.TestCase):
    """Primary batch-grouping function."""

    def test_basic_grouping(self):
        items = [
            _make_item("A", 1),
            _make_item("A", 2),
            _make_item("B", 3),
            _make_item("C", 4),
        ]
        batches = group_by_tag(items)
        self.assertEqual(len(batches), 3)
        self.assertEqual(batches[0].tag, "A")
        self.assertEqual(batches[1].tag, "B")
        self.assertEqual(batches[2].tag, "C")

    def test_order_preserved_within_tag(self):
        items = [
            _make_item("A", 3),
            _make_item("A", 1),
            _make_item("A", 2),
        ]
        batches = group_by_tag(items)
        self.assertEqual(len(batches), 1)
        ids = [item.id for item in batches[0].items]
        self.assertEqual(ids, [1, 2, 3])

    def test_split_into_multiple_batches(self):
        items = [_make_item("A", i) for i in range(20)]
        batches = group_by_tag(items, max_per_batch=15)
        self.assertEqual(len(batches), 2)
        self.assertEqual(batches[0].item_count, 15)
        self.assertEqual(batches[1].item_count, 5)
        self.assertEqual(batches[0].batch_index, 0)
        self.assertEqual(batches[1].batch_index, 1)
        self.assertEqual(batches[0].total_batches, 2)
        self.assertEqual(batches[1].total_batches, 2)

    def test_small_batch(self):
        items = [_make_item("A", i) for i in range(5)]
        batches = group_by_tag(items)
        self.assertEqual(len(batches), 1)
        self.assertEqual(batches[0].item_count, 5)

    def test_empty_tags_skipped(self):
        items = [
            _make_item("", 1),
            _make_item("A", 2),
            _make_item("", 3),
        ]
        batches = group_by_tag(items)
        self.assertEqual(len(batches), 1)
        self.assertEqual(batches[0].tag, "A")

    def test_empty_items(self):
        batches = group_by_tag([])
        self.assertEqual(batches, [])

    def test_custom_max_per_batch(self):
        items = [_make_item("A", i) for i in range(10)]
        batches = group_by_tag(items, max_per_batch=3)
        self.assertEqual(len(batches), 4)
        counts = [b.item_count for b in batches]
        self.assertEqual(counts, [3, 3, 3, 1])

    def test_batch_metadata(self):
        # Two tags, second tag has 20 items -> 2 batches
        items = [_make_item("A", i) for i in range(15)]
        items += [_make_item("B", i) for i in range(20)]
        batches = group_by_tag(items, max_per_batch=15)

        batch_a = batches[0]
        batch_b_1 = batches[1]
        batch_b_2 = batches[2]

        self.assertEqual(batch_a.tag, "A")
        self.assertEqual(batch_a.batch_index, 0)
        self.assertEqual(batch_a.total_batches, 1)
        self.assertEqual(batch_a.item_count, 15)

        self.assertEqual(batch_b_1.tag, "B")
        self.assertEqual(batch_b_1.batch_index, 0)
        self.assertEqual(batch_b_1.total_batches, 2)
        self.assertEqual(batch_b_1.item_count, 15)

        self.assertEqual(batch_b_2.tag, "B")
        self.assertEqual(batch_b_2.batch_index, 1)
        self.assertEqual(batch_b_2.total_batches, 2)
        self.assertEqual(batch_b_2.item_count, 5)

    def test_single_item_per_batch(self):
        items = [_make_item("A", i) for i in range(3)]
        batches = group_by_tag(items, max_per_batch=1)
        self.assertEqual(len(batches), 3)
        for i, b in enumerate(batches):
            self.assertEqual(b.item_count, 1)
            self.assertEqual(b.batch_index, i)

    def test_missing_tag_attr(self):
        class BadItem:
            pass

        with self.assertRaises(AttributeError):
            group_by_tag([BadItem()])

    def test_custom_prefix(self):
        items = [_make_item("A", 1)]
        batches = group_by_tag(items, prefix="code")
        self.assertEqual(batches[0].batch_id, "code_A_batch_00")

    def test_multiple_tags_split(self):
        # Ensure batches from different tags are flattened correctly
        items = (
            [_make_item("A", i) for i in range(20)]
            + [_make_item("B", i) for i in range(15)]
            + [_make_item("C", i) for i in range(4)]
        )
        batches = group_by_tag(items, max_per_batch=15)
        self.assertEqual(len(batches), 4)  # A: 2, B: 1, C: 1
        self.assertEqual(batches[0].tag, "A")
        self.assertEqual(batches[1].tag, "A")
        self.assertEqual(batches[2].tag, "B")
        self.assertEqual(batches[3].tag, "C")

    def test_batch_id_across_multiple_batches(self):
        items = [_make_item("X", i) for i in range(17)]
        batches = group_by_tag(items, max_per_batch=15)
        self.assertEqual(len(batches), 2)
        self.assertEqual(batches[0].batch_id, "tag_X_batch_00")
        self.assertEqual(batches[1].batch_id, "tag_X_batch_01")

    def test_invalid_max_per_batch(self):
        with self.assertRaises(ValueError):
            group_by_tag([], max_per_batch=0)


class TestBatchableItemProtocol(unittest.TestCase):
    """Runtime protocol check."""

    def test_valid_item_passes_protocol(self):
        item = _make_item("A", 1)
        self.assertIsInstance(item, BatchableItem)

    def test_invalid_item_fails_protocol(self):
        class NotBatchable:
            pass

        self.assertNotIsInstance(NotBatchable(), BatchableItem)


class TestBatchDataclass(unittest.TestCase):
    """Batch dataclass invariants."""

    def test_item_count_computed(self):
        b = Batch(tag="T", items=[1, 2, 3], batch_index=0, total_batches=1)
        self.assertEqual(b.item_count, 3)

    def test_item_count_reflects_items(self):
        b = Batch(tag="T", items=[], batch_index=0, total_batches=1)
        self.assertEqual(b.item_count, 0)


# ── group_by_similarity ────────────────────────────────────────────────────


class TestGroupBySimilarity(unittest.TestCase):
    """Wrap similarity clusters into Batch objects."""

    def test_clusters_only_no_misc(self):
        items_a = [_make_item("T1", i) for i in range(5)]
        items_b = [_make_item("T1", i) for i in range(5, 10)]
        batches = group_by_similarity("T1", [items_a, items_b], [], prefix="code")
        self.assertEqual(len(batches), 2)
        self.assertEqual(batches[0].tag, "T1")
        self.assertEqual(batches[0].item_count, 5)
        self.assertEqual(batches[0].batch_index, 0)
        self.assertEqual(batches[0].total_batches, 2)
        self.assertIn("code_T1_batch_00", batches[0].batch_id)
        self.assertEqual(batches[1].item_count, 5)
        self.assertEqual(batches[1].batch_index, 1)

    def test_misc_batch_last(self):
        items_a = [_make_item("T1", i) for i in range(5)]
        misc = [_make_item("T1", i) for i in range(5, 8)]
        batches = group_by_similarity("T1", [items_a], misc, prefix="code")
        self.assertEqual(len(batches), 2)
        self.assertEqual(batches[0].tag, "T1")
        self.assertEqual(batches[1].tag, "T1")
        self.assertEqual(batches[0].item_count, 5)
        self.assertEqual(batches[1].item_count, 3)
        self.assertEqual(batches[1].batch_index, 1)
        self.assertEqual(batches[1].total_batches, 2)
        self.assertIn("misc", batches[1].batch_id)

    def test_no_clusters_all_misc(self):
        misc = [_make_item("T1", i) for i in range(10)]
        batches = group_by_similarity("T1", [], misc, prefix="code")
        self.assertEqual(len(batches), 1)
        self.assertEqual(batches[0].item_count, 10)
        self.assertIn("misc", batches[0].batch_id)

    def test_empty_clusters_and_misc(self):
        batches = group_by_similarity("T1", [], [], prefix="code")
        self.assertEqual(len(batches), 0)

    def test_multiple_clusters_with_correct_indexing(self):
        c1 = [_make_item("T1", i) for i in range(5)]
        c2 = [_make_item("T1", i) for i in range(5, 10)]
        c3 = [_make_item("T1", i) for i in range(10, 15)]
        misc = [_make_item("T1", i) for i in range(15, 17)]
        batches = group_by_similarity("T1", [c1, c2, c3], misc, prefix="code")
        self.assertEqual(len(batches), 4)
        self.assertEqual(batches[0].batch_index, 0)
        self.assertEqual(batches[1].batch_index, 1)
        self.assertEqual(batches[2].batch_index, 2)
        self.assertEqual(batches[3].batch_index, 3)
        self.assertEqual(batches[0].total_batches, 4)
        self.assertEqual(batches[3].total_batches, 4)
        self.assertIn("misc", batches[3].batch_id)

    def test_items_retain_identity(self):
        items = [_make_item("T1", i) for i in range(5)]
        batches = group_by_similarity("T1", [items], [], prefix="code")
        self.assertIs(batches[0].items[0], items[0])


if __name__ == "__main__":
    unittest.main()
