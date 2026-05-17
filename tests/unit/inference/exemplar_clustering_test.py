"""Tests for inference/exemplar_clustering.py — similarity-based transitivity clustering."""

# flake8: noqa: E402
import sys
import unittest
from pathlib import Path
from typing import cast

sys.path.insert(
    0, str(Path(__file__).parent.parent.parent.parent / "src" / "python")
)  # noqa: E402

import numpy as np
from inference.batching import BatchableItem
from inference.exemplar_clustering import cluster_by_similarity


def _make_item(item_id: int, tag: str = "T1") -> BatchableItem:
    return cast(BatchableItem, type("Item", (), {"id": item_id, "tag": tag})())


class TestClusterBySimilarity(unittest.TestCase):
    """Threshold-based transitivity clustering."""

    def test_simple_two_clusters(self):
        items = [_make_item(i) for i in range(10)]
        # Items 0-4 similar to each other (sim=0.9), items 5-9 similar (sim=0.9)
        sim = np.zeros((10, 10), dtype="float32")
        for i in range(5):
            for j in range(5):
                sim[i, j] = 0.9
        for i in range(5, 10):
            for j in range(5, 10):
                sim[i, j] = 0.9
        # Cross-group similarity is low
        for i in range(5):
            for j in range(5, 10):
                sim[i, j] = 0.1
        np.fill_diagonal(sim, 1.0)

        clusters, misc = cluster_by_similarity(items, sim, threshold=0.5)
        self.assertEqual(len(clusters), 2)
        self.assertEqual(len(misc), 0)
        ids = [{e.id for e in c} for c in clusters]
        self.assertIn({0, 1, 2, 3, 4}, ids)
        self.assertIn({5, 6, 7, 8, 9}, ids)

    def test_all_below_threshold(self):
        items = [_make_item(i) for i in range(10)]
        sim = np.full((10, 10), 0.1, dtype="float32")
        np.fill_diagonal(sim, 1.0)

        clusters, misc = cluster_by_similarity(items, sim, threshold=0.5)
        self.assertEqual(len(clusters), 0)
        self.assertEqual(len(misc), 10)

    def test_all_above_threshold_single_cluster(self):
        items = [_make_item(i) for i in range(10)]
        sim = np.full((10, 10), 0.9, dtype="float32")
        np.fill_diagonal(sim, 1.0)

        clusters, misc = cluster_by_similarity(items, sim, threshold=0.5)
        self.assertEqual(len(clusters), 1)
        self.assertEqual(len(clusters[0]), 10)
        self.assertEqual(len(misc), 0)

    def test_small_cluster_padding(self):
        items = [_make_item(i) for i in range(10)]
        # Group A: items 0-1 (size 2, sim 0.9 internal)
        # Group B: items 2-6 (size 5, sim 0.9 internal) — already >= 5
        # Items 7, 8, 9: isolated (sim 0.1 to everyone) — available to pad Group A
        sim = np.full((10, 10), 0.1, dtype="float32")
        np.fill_diagonal(sim, 1.0)
        sim[0, 1] = sim[1, 0] = 0.9
        for i in range(2, 7):
            for j in range(2, 7):
                sim[i, j] = 0.9
        # Group A has moderate sim to items 7-9 (below threshold, but usable for padding)
        for pi in [7, 8, 9]:
            sim[0, pi] = sim[pi, 0] = 0.49
            sim[1, pi] = sim[pi, 1] = 0.49

        clusters, misc = cluster_by_similarity(
            items, sim, threshold=0.5, min_cluster_size=5
        )
        # Group B (2-6) is cluster 1 (size 5)
        # Group A (0-1) gets padded with 7,8,9 from pool → size 5 cluster
        self.assertEqual(len(clusters), 2)
        sizes = sorted(len(c) for c in clusters)
        self.assertEqual(sizes, [5, 5])
        self.assertEqual(len(misc), 0)

    def test_cluster_padding_pulls_from_small_groups(self):
        items = [_make_item(i) for i in range(7)]
        # Group B: items 2-5 (size 4, sim 0.9 internal) — needs padding
        # Group A: items 0-1 (size 2, sim 0.9 internal)
        # Item 6: isolated (sim 0.1)
        sim = np.full((7, 7), 0.1, dtype="float32")
        np.fill_diagonal(sim, 1.0)
        sim[0, 1] = sim[1, 0] = 0.9
        for i in range(2, 6):
            for j in range(2, 6):
                sim[i, j] = 0.9
        # Cross-group sim below threshold (for Union-Find separation)
        # but usable for greedy padding
        sim[0, 2] = sim[2, 0] = 0.49
        sim[1, 6] = sim[6, 1] = 0.49
        sim[2, 6] = sim[6, 2] = 0.49

        clusters, misc = cluster_by_similarity(
            items, sim, threshold=0.5, min_cluster_size=5
        )
        # Group B (2-5, size 4) is first → pads to 5 by pulling nearest from pool
        # Group A (0-1, size 2) tries to pad but only item 6 remains → needs 3, only 1 avail
        self.assertEqual(len(clusters), 1)
        self.assertEqual(len(clusters[0]), 5)
        self.assertEqual(len(misc), 2)
        misc_ids = {e.id for e in misc}
        self.assertLessEqual(misc_ids, {0, 1, 6})

    def test_empty_items(self):
        clusters, misc = cluster_by_similarity(
            [], np.zeros((0, 0), dtype="float32"), threshold=0.5
        )
        self.assertEqual(clusters, [])
        self.assertEqual(misc, [])

    def test_single_item(self):
        items = [_make_item(1)]
        sim = np.ones((1, 1), dtype="float32")

        clusters, misc = cluster_by_similarity(
            items, sim, threshold=0.5, min_cluster_size=5
        )
        self.assertEqual(len(clusters), 0)
        self.assertEqual(len(misc), 1)

    def test_transitive_closure(self):
        items = [_make_item(i) for i in range(5)]
        # A chain: 0-1 (0.9), 1-2 (0.9), 2-3 (0.9), 3-4 (0.9)
        # Non-adjacent pairs are below threshold
        sim = np.full((5, 5), 0.1, dtype="float32")
        np.fill_diagonal(sim, 1.0)
        sim[0, 1] = sim[1, 0] = 0.9
        sim[1, 2] = sim[2, 1] = 0.9
        sim[2, 3] = sim[3, 2] = 0.9
        sim[3, 4] = sim[4, 3] = 0.9

        clusters, misc = cluster_by_similarity(items, sim, threshold=0.5)
        # All 5 items should be in one cluster via transitive closure
        self.assertEqual(len(clusters), 1)
        self.assertEqual(len(clusters[0]), 5)
        self.assertEqual(len(misc), 0)

    def test_min_cluster_size_exact(self):
        items = [_make_item(i) for i in range(5)]
        sim = np.full((5, 5), 0.9, dtype="float32")
        np.fill_diagonal(sim, 1.0)

        clusters, misc = cluster_by_similarity(
            items, sim, threshold=0.5, min_cluster_size=5
        )
        self.assertEqual(len(clusters), 1)
        self.assertEqual(len(clusters[0]), 5)
        self.assertEqual(len(misc), 0)

    def test_small_cluster_with_pool_less_than_five(self):
        items = [_make_item(i) for i in range(6)]
        # Group A: items 0-1 (size 2, sim 0.9)
        # Group B: items 2-5 (size 4, sim 0.9) — < 5, needs padding
        # Cross sim below threshold so Union-Find keeps groups separate
        sim = np.full((6, 6), 0.1, dtype="float32")
        np.fill_diagonal(sim, 1.0)
        sim[0, 1] = sim[1, 0] = 0.9
        for i in range(2, 6):
            for j in range(2, 6):
                sim[i, j] = 0.9
        # Modest cross sim (below threshold, usable for greedy padding)
        for i in range(2):
            for j in range(2, 6):
                sim[i, j] = 0.49
                sim[j, i] = 0.49

        clusters, misc = cluster_by_similarity(
            items, sim, threshold=0.5, min_cluster_size=5
        )
        # Group B (2-5, size 4) is largest → pads to 5 by pulling 1 item from pool (item 0 or 1)
        # Group A (remaining pool item) size 1 → can't pad → goes to misc
        self.assertEqual(len(clusters), 1)
        self.assertEqual(len(clusters[0]), 5)
        self.assertEqual(len(misc), 1)

    def test_misc_contains_leftover(self):
        items = [_make_item(i) for i in range(8)]
        sim = np.full((8, 8), 0.1, dtype="float32")
        np.fill_diagonal(sim, 1.0)
        # Items 0-4 form a tight cluster
        for i in range(5):
            for j in range(5):
                sim[i, j] = 0.9
        # Items 5, 6, 7 are isolated (low sim to everything)
        sim[5, 6] = sim[6, 5] = 0.3
        sim[5, 7] = sim[7, 5] = 0.3
        sim[6, 7] = sim[7, 6] = 0.3

        clusters, misc = cluster_by_similarity(
            items, sim, threshold=0.5, min_cluster_size=5
        )
        self.assertEqual(len(clusters), 1)
        self.assertEqual(len(clusters[0]), 5)
        self.assertEqual(len(misc), 3)
        misc_ids = {e.id for e in misc}
        self.assertEqual(misc_ids, {5, 6, 7})


if __name__ == "__main__":
    unittest.main()
