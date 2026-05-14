"""Tests for inference/inference_status_queries.py — read/query operations."""

# flake8: noqa: E402
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(
    0,
    str(Path(__file__).parent.parent.parent.parent / "src" / "python"),
)

import duckdb
from inference.inference_status_crud import (
    init_inference_status_table,
    set_status,
    set_status_draft,
)
from inference.inference_status_queries import (
    get_pending_items,
    get_stage_summary,
    get_status,
    reset_inference_status,
)
from inference.inference_status_types import (
    APPROVED,
    DRAFT,
    GENERATED,
    PENDING,
    REJECTED,
    STAGE_CODE,
    STAGE_THEME,
)


def _make_con(tmpdir: Path) -> duckdb.DuckDBPyConnection:
    con = duckdb.connect(str(tmpdir / "test.duckdb"))
    init_inference_status_table(con)
    return con


# ── get_pending_items ───────────────────────────────────────────────────────


class TestGetPendingItems(unittest.TestCase):
    """AC #3: Returns only items needing inference.
    AC #4: After HITL edits, only changed items returned."""

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())
        self.con = _make_con(self.tmpdir)

    def tearDown(self):
        self.con.close()
        import shutil

        shutil.rmtree(self.tmpdir)

    def test_returns_pending_items(self):
        set_status(self.con, "e1", "exemplar", STAGE_CODE, PENDING)
        set_status(self.con, "e2", "exemplar", STAGE_CODE, GENERATED)
        set_status(self.con, "e3", "exemplar", STAGE_CODE, PENDING)
        items = get_pending_items(self.con, STAGE_CODE)
        self.assertCountEqual(items, ["e1", "e3"])

    def test_returns_draft_items(self):
        set_status(self.con, "e1", "exemplar", STAGE_CODE, DRAFT)
        set_status(self.con, "e2", "exemplar", STAGE_CODE, APPROVED)
        items = get_pending_items(self.con, STAGE_CODE)
        self.assertEqual(items, ["e1"])

    def test_skips_approved_and_rejected(self):
        set_status(self.con, "e1", "exemplar", STAGE_CODE, PENDING)
        set_status(self.con, "e2", "exemplar", STAGE_CODE, APPROVED)
        set_status(self.con, "e3", "exemplar", STAGE_CODE, REJECTED)
        items = get_pending_items(self.con, STAGE_CODE)
        self.assertEqual(items, ["e1"])

    def test_empty_table_returns_empty_list(self):
        items = get_pending_items(self.con, STAGE_CODE)
        self.assertEqual(items, [])

    def test_ordered_by_entity_id(self):
        set_status(self.con, "z", "exemplar", STAGE_CODE, PENDING)
        set_status(self.con, "a", "exemplar", STAGE_CODE, PENDING)
        items = get_pending_items(self.con, STAGE_CODE)
        self.assertEqual(items, ["a", "z"])

    def test_invalid_stage_raises(self):
        with self.assertRaises(ValueError):
            get_pending_items(self.con, "invalid_stage")

    def test_re_run_after_edit_returns_changed_only(self):
        """AC #4: After HITL edits, only changed items returned."""
        set_status(self.con, "e1", "exemplar", STAGE_CODE, GENERATED)
        set_status(self.con, "e2", "exemplar", STAGE_CODE, APPROVED)
        set_status(self.con, "e3", "exemplar", STAGE_CODE, PENDING)
        before = get_pending_items(self.con, STAGE_CODE)
        self.assertEqual(before, ["e3"])
        set_status_draft(self.con, "e1", "exemplar", STAGE_CODE)
        after = get_pending_items(self.con, STAGE_CODE)
        self.assertCountEqual(after, ["e1", "e3"])

    def test_get_pending_items_by_tag_no_parquet(self):
        set_status(self.con, "ex1", "exemplar", STAGE_CODE, PENDING)
        set_status(self.con, "ex2", "exemplar", STAGE_CODE, PENDING)
        with self.assertRaises(duckdb.Error):
            get_pending_items(self.con, STAGE_CODE, tag="resilience")


# ── get_status ──────────────────────────────────────────────────────────────


class TestGetStatus(unittest.TestCase):
    """AC #5: Query single row for debugging."""

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())
        self.con = _make_con(self.tmpdir)

    def tearDown(self):
        self.con.close()
        import shutil

        shutil.rmtree(self.tmpdir)

    def test_returns_row_when_exists(self):
        set_status(self.con, "e1", "exemplar", STAGE_CODE, GENERATED)
        row = get_status(self.con, "e1", "exemplar", STAGE_CODE)
        self.assertEqual(row["entity_id"], "e1")
        self.assertEqual(row["entity_type"], "exemplar")
        self.assertEqual(row["stage"], STAGE_CODE)
        self.assertEqual(row["status"], GENERATED)
        self.assertIsInstance(row, dict)

    def test_returns_none_when_not_found(self):
        row = get_status(self.con, "nonexistent", "exemplar", STAGE_CODE)
        self.assertIsNone(row)

    def test_all_fields_present(self):
        set_status(self.con, "e1", "exemplar", STAGE_CODE, GENERATED)
        row = get_status(self.con, "e1", "exemplar", STAGE_CODE)
        expected_keys = {
            "entity_id",
            "entity_type",
            "stage",
            "status",
            "last_attempt_at",
            "attempts",
        }
        self.assertEqual(set(row.keys()), expected_keys)


# ── get_stage_summary ───────────────────────────────────────────────────────


class TestGetStageSummary(unittest.TestCase):
    """Aggregate counts by status for a given stage."""

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())
        self.con = _make_con(self.tmpdir)

    def tearDown(self):
        self.con.close()
        import shutil

        shutil.rmtree(self.tmpdir)

    def test_summary_counts(self):
        set_status(self.con, "e1", "exemplar", STAGE_CODE, PENDING)
        set_status(self.con, "e2", "exemplar", STAGE_CODE, GENERATED)
        set_status(self.con, "e3", "exemplar", STAGE_CODE, GENERATED)
        set_status(self.con, "e4", "exemplar", STAGE_CODE, APPROVED)
        summary = get_stage_summary(self.con, STAGE_CODE)
        self.assertEqual(summary[PENDING], 1)
        self.assertEqual(summary[GENERATED], 2)
        self.assertEqual(summary[APPROVED], 1)
        self.assertEqual(summary[REJECTED], 0)
        self.assertEqual(summary[DRAFT], 0)

    def test_summary_empty_stage(self):
        summary = get_stage_summary(self.con, STAGE_CODE)
        self.assertEqual(summary[PENDING], 0)

    def test_summary_separates_stages(self):
        set_status(self.con, "e1", "exemplar", STAGE_CODE, GENERATED)
        set_status(self.con, "t1", "theme", STAGE_THEME, PENDING)
        code_s = get_stage_summary(self.con, STAGE_CODE)
        theme_s = get_stage_summary(self.con, STAGE_THEME)
        self.assertEqual(code_s[GENERATED], 1)
        self.assertEqual(theme_s[PENDING], 1)


# ── reset_inference_status ──────────────────────────────────────────────────


class TestResetInferenceStatus(unittest.TestCase):
    """Full table wipe."""

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())
        self.con = _make_con(self.tmpdir)

    def tearDown(self):
        self.con.close()
        import shutil

        shutil.rmtree(self.tmpdir)

    def test_reset_clears_all_rows(self):
        set_status(self.con, "e1", "exemplar", STAGE_CODE, GENERATED)
        set_status(self.con, "e2", "exemplar", STAGE_CODE, PENDING)
        reset_inference_status(self.con)
        count = self.con.execute("SELECT COUNT(*) FROM inference_status").fetchone()[0]
        self.assertEqual(count, 0)

    def test_reset_empty_table(self):
        reset_inference_status(self.con)
        count = self.con.execute("SELECT COUNT(*) FROM inference_status").fetchone()[0]
        self.assertEqual(count, 0)


if __name__ == "__main__":
    unittest.main()
