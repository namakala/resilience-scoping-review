"""Tests for inference/inference_status_crud.py — write operations."""

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
    batch_set_status,
    init_inference_status_table,
    set_status,
    set_status_draft,
)
from inference.inference_status_queries import get_pending_items, get_status
from inference.inference_status_types import (
    APPROVED,
    DRAFT,
    GENERATED,
    PENDING,
    STAGE_CODE,
    STAGE_THEME,
)


def _make_con(tmpdir: Path) -> duckdb.DuckDBPyConnection:
    con = duckdb.connect(str(tmpdir / "test.duckdb"))
    init_inference_status_table(con)
    return con


# ── set_status ──────────────────────────────────────────────────────────────


class TestSetStatus(unittest.TestCase):
    """AC #1: set_status creates rows and handles upsert."""

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())
        self.con = _make_con(self.tmpdir)

    def tearDown(self):
        self.con.close()
        import shutil

        shutil.rmtree(self.tmpdir)

    def test_creates_row(self):
        set_status(self.con, "ex1", "exemplar", STAGE_CODE, PENDING)
        row = get_status(self.con, "ex1", "exemplar", STAGE_CODE)
        self.assertIsNotNone(row)
        self.assertEqual(row["status"], PENDING)
        self.assertEqual(row["attempts"], 1)

    def test_generated_sets_timestamp(self):
        set_status(self.con, "ex1", "exemplar", STAGE_CODE, GENERATED)
        row = get_status(self.con, "ex1", "exemplar", STAGE_CODE)
        self.assertIsNotNone(row["last_attempt_at"])

    def test_non_generated_no_timestamp(self):
        set_status(self.con, "ex1", "exemplar", STAGE_CODE, APPROVED)
        row = get_status(self.con, "ex1", "exemplar", STAGE_CODE)
        self.assertIsNone(row["last_attempt_at"])

    def test_upsert_updates_status_and_increments(self):
        set_status(self.con, "ex1", "exemplar", STAGE_CODE, GENERATED)
        set_status(self.con, "ex1", "exemplar", STAGE_CODE, APPROVED)
        row = get_status(self.con, "ex1", "exemplar", STAGE_CODE)
        self.assertEqual(row["status"], APPROVED)
        self.assertEqual(row["attempts"], 2)

    def test_multiple_entities_independent(self):
        set_status(self.con, "ex1", "exemplar", STAGE_CODE, GENERATED)
        set_status(self.con, "ex2", "exemplar", STAGE_CODE, PENDING)
        e1 = get_status(self.con, "ex1", "exemplar", STAGE_CODE)
        e2 = get_status(self.con, "ex2", "exemplar", STAGE_CODE)
        self.assertEqual(e1["status"], GENERATED)
        self.assertEqual(e2["status"], PENDING)

    def test_same_entity_different_stages(self):
        set_status(self.con, "c1", "code", STAGE_CODE, APPROVED)
        set_status(self.con, "c1", "code", STAGE_THEME, PENDING)
        code = get_status(self.con, "c1", "code", STAGE_CODE)
        theme = get_status(self.con, "c1", "code", STAGE_THEME)
        self.assertEqual(code["status"], APPROVED)
        self.assertEqual(theme["status"], PENDING)


# ── set_status_draft ────────────────────────────────────────────────────────


class TestSetStatusDraft(unittest.TestCase):
    """AC #2: Edits reset status to draft and increment attempts."""

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())
        self.con = _make_con(self.tmpdir)

    def tearDown(self):
        self.con.close()
        import shutil

        shutil.rmtree(self.tmpdir)

    def test_draft_after_approved(self):
        set_status(self.con, "c1", "code", STAGE_CODE, APPROVED)
        set_status_draft(self.con, "c1", "code", STAGE_CODE)
        row = get_status(self.con, "c1", "code", STAGE_CODE)
        self.assertEqual(row["status"], DRAFT)
        self.assertEqual(row["attempts"], 2)

    def test_multiple_edits_increment_attempts(self):
        set_status(self.con, "c1", "code", STAGE_CODE, GENERATED)
        set_status_draft(self.con, "c1", "code", STAGE_CODE)
        set_status_draft(self.con, "c1", "code", STAGE_CODE)
        row = get_status(self.con, "c1", "code", STAGE_CODE)
        self.assertEqual(row["status"], DRAFT)
        self.assertEqual(row["attempts"], 3)

    def test_draft_on_new_entity_starts_at_1(self):
        set_status_draft(self.con, "new1", "code", STAGE_THEME)
        row = get_status(self.con, "new1", "code", STAGE_THEME)
        self.assertEqual(row["status"], DRAFT)
        self.assertEqual(row["attempts"], 1)


# ── batch_set_status ────────────────────────────────────────────────────────


class TestBatchSetStatus(unittest.TestCase):
    """Bulk upsert for use after inference runs."""

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())
        self.con = _make_con(self.tmpdir)

    def tearDown(self):
        self.con.close()
        import shutil

        shutil.rmtree(self.tmpdir)

    def test_batch_inserts_multiple_rows(self):
        updates = [
            ("e1", "exemplar", STAGE_CODE, GENERATED),
            ("e2", "exemplar", STAGE_CODE, GENERATED),
            ("e3", "exemplar", STAGE_CODE, PENDING),
        ]
        batch_set_status(self.con, updates)
        items = get_pending_items(self.con, STAGE_CODE)
        self.assertEqual(items, ["e3"])

    def test_batch_updates_existing_rows(self):
        set_status(self.con, "e1", "exemplar", STAGE_CODE, PENDING)
        set_status(self.con, "e2", "exemplar", STAGE_CODE, GENERATED)
        batch_set_status(
            self.con,
            [
                ("e1", "exemplar", STAGE_CODE, GENERATED),
                ("e2", "exemplar", STAGE_CODE, APPROVED),
            ],
        )
        self.assertEqual(get_pending_items(self.con, STAGE_CODE), [])

    def test_batch_empty_list(self):
        batch_set_status(self.con, [])
        self.assertEqual(get_pending_items(self.con, STAGE_CODE), [])

    def test_batch_generated_sets_timestamp(self):
        batch_set_status(self.con, [("e1", "exemplar", STAGE_CODE, GENERATED)])
        row = get_status(self.con, "e1", "exemplar", STAGE_CODE)
        self.assertIsNotNone(row["last_attempt_at"])


if __name__ == "__main__":
    unittest.main()
