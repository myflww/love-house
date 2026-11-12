"""Usage receipts are metadata-only, scoped and compare-and-ack durable."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import time
import unittest
from unittest.mock import patch

from nkb.errors import StorageError, ValidationError
from nkb.service.usage import DAY, UsageJournal


class UsageJournalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="love-house-usage-test-")
        self.root = Path(self.temp.name)
        self.stamp = 20000 * DAY + 40000
        self.journal = UsageJournal(self.root, clock=lambda: self.stamp)

    def tearDown(self):
        self.temp.cleanup()

    def test_production_context_closes_connection_after_success_and_sqlite_failure(self):
        original=sqlite3.connect
        opened=[]
        def connect(*args,**kwargs):
            db=original(*args,**kwargs);opened.append(db);return db
        with patch('nkb.service.usage.sqlite3.connect',side_effect=connect):
            self.journal.enqueue('one',['closed-handle'],'recall')
            self.journal.pending('one')
            with self.assertRaises(StorageError):
                with self.journal.db() as db:
                    db.execute('SELECT * FROM deliberately_missing_table')
        self.assertGreaterEqual(len(opened),3)
        for db in opened:
            with self.assertRaises(sqlite3.ProgrammingError):db.execute('SELECT 1')

    def test_locked_auxiliary_database_fails_quickly_instead_of_blocking_capture(self):
        locked=sqlite3.connect(self.journal.path)
        try:
            locked.execute('BEGIN IMMEDIATE')
            started=time.monotonic()
            with self.assertRaises(StorageError):self.journal.enqueue('one',['a'],'recall')
            self.assertLess(time.monotonic()-started,0.5)
        finally:
            locked.rollback();locked.close()

    def test_corrupt_optional_pending_metadata_is_rejected_without_echoing_it(self):
        self.journal.enqueue('one',['a'],'recall')
        with closing(sqlite3.connect(self.journal.path)) as db, db:
            db.execute("UPDATE memory_usage SET pending_at=-1 WHERE node_id='a'")
        with self.assertRaises(StorageError) as caught:self.journal.pending('one')
        self.assertNotIn('node_id',str(caught.exception))

    def test_enqueue_is_scoped_deduplicated_and_does_not_contain_content(self):
        self.assertEqual(self.journal.enqueue("one", ["a", "a", "b"], "recall"), {"queued": 2, "ignored": 0})
        self.assertEqual(self.journal.enqueue("one", ["a"], "recall"), {"queued": 0, "ignored": 1})
        self.journal.enqueue("other", ["a"], "recall")
        rows = self.journal.pending("one")
        self.assertEqual({r["node_id"] for r in rows}, {"a", "b"})
        self.assertTrue(all(set(r) == {"library_id", "node_id", "kind", "day", "at"} for r in rows))
        self.assertEqual(self.journal.counts("one"), {"pending": 2, "by_kind": {"recall": 2, "mention": 0}})
        with closing(sqlite3.connect(self.journal.path)) as db, db:
            columns = {r[1] for r in db.execute("PRAGMA table_info(memory_usage)")}
        self.assertEqual(columns, {"library_id", "node_id", "kind", "last_at", "last_day", "pending_at", "pending_day", "applied_at"})

    def test_kind_is_independent_and_same_kind_waits_rolling_24_hours(self):
        self.journal.enqueue("one", ["a"], "recall", at=self.stamp)
        self.journal.enqueue("one", ["a"], "mention", at=self.stamp)
        self.assertEqual(len(self.journal.pending("one")), 2)
        later_midnight = (int(self.stamp // DAY) + 1) * DAY + 1
        self.assertEqual(self.journal.enqueue("one", ["a"], "recall", at=later_midnight)["queued"], 0)
        self.assertEqual(self.journal.enqueue("one", ["a"], "recall", at=self.stamp + DAY)["queued"], 1)

    def test_applied_marker_survives_restart_and_cannot_repeat_same_day(self):
        self.journal.enqueue("one", ["a"], "recall")
        rows = self.journal.pending("one")
        self.assertEqual(self.journal.applied(rows), 1)
        reopened = UsageJournal(self.root, clock=lambda: self.stamp + 10)
        self.assertEqual(reopened.pending("one"), [])
        self.assertEqual(reopened.applied(rows), 0)
        self.assertEqual(reopened.enqueue("one", ["a"], "recall")["queued"], 0)
        self.assertEqual(reopened.enqueue("one", ["a"], "recall", at=self.stamp + DAY)["queued"], 1)

    def test_unacknowledged_use_remains_pending_and_only_latest_day_is_retained(self):
        self.journal.enqueue("one", ["a"], "recall")
        before = self.journal.pending("one")
        self.assertEqual(UsageJournal(self.root).pending("one"), before)
        self.journal.enqueue("one", ["a"], "recall", at=self.stamp + 2 * DAY)
        pending = self.journal.pending("one")
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]["at"], self.stamp + 2 * DAY)
        self.assertEqual(self.journal.applied(before), 0)  # Old graph completion cannot eat a new event.
        self.assertEqual(self.journal.pending("one"), pending)
        self.assertEqual(self.journal.applied(pending), 1)

    def test_out_of_order_old_use_never_rewinds_last_seen_or_pending(self):
        self.journal.enqueue("one", ["a"], "mention", at=self.stamp)
        before = self.journal.pending("one")
        self.assertEqual(self.journal.enqueue("one", ["a"], "mention", at=self.stamp - 2 * DAY)["queued"], 0)
        self.assertEqual(self.journal.pending("one"), before)

    def test_forgetting_is_scoped_and_unavailable_ids_can_be_discarded(self):
        for library in ("one", "other"):
            for kind in ("recall", "mention"):
                self.journal.enqueue(library, ["a", "b"], kind)
        self.assertEqual(self.journal.forget("one", ["a"]), 2)
        self.assertEqual({r["node_id"] for r in self.journal.pending("one")}, {"b"})
        self.assertEqual(len(self.journal.pending("other")), 4)
        self.assertEqual(self.journal.discard("one", ["b"]), 2)
        self.assertEqual(self.journal.pending("one"), [])
        self.assertEqual(self.journal.forget("other"), 4)

    def test_metadata_does_not_grow_by_day_or_use_count(self):
        for day in range(60):
            self.journal.enqueue("one", ["a", "b"], "recall", at=self.stamp + day * DAY)
            self.journal.applied(self.journal.pending("one"))
        with closing(sqlite3.connect(self.journal.path)) as db, db:
            count = db.execute("SELECT COUNT(*) FROM memory_usage").fetchone()[0]
        self.assertEqual(count, 2)
        self.assertEqual(self.journal.counts("one")["pending"], 0)

    def test_parallel_duplicate_enqueues_accept_once_and_all_handles_close(self):
        def record(_):
            return UsageJournal(self.root).enqueue("one", ["a"], "recall", at=self.stamp)["queued"]
        with ThreadPoolExecutor(max_workers=4) as pool:
            accepted = list(pool.map(record, range(12)))
        self.assertEqual(sum(accepted), 1)
        self.assertEqual(len(self.journal.pending("one")), 1)
        # On Windows an unclosed connection would make temporary cleanup fail.
        moved = self.root / "moved.sqlite3"
        self.journal.path.rename(moved)
        moved.rename(self.journal.path)

    def test_applied_batch_validates_every_row_before_touching_any(self):
        self.journal.enqueue("one", ["a", "b"], "recall")
        rows = self.journal.pending("one")
        wrong = {**rows[1], "day": rows[1]["day"] + 1}
        with self.assertRaises(ValidationError):
            self.journal.applied([rows[0], wrong])
        self.assertEqual(self.journal.pending("one"), rows)

    def test_failed_ack_rolls_back_all_rows_and_preserves_pending_for_retry(self):
        self.journal.enqueue("one", ["a", "b"], "recall")
        rows = self.journal.pending("one")
        with self.journal.db() as db:
            db.execute("""CREATE TRIGGER fail_ack BEFORE UPDATE OF pending_at ON memory_usage
                WHEN OLD.node_id='b' AND NEW.pending_at IS NULL
                BEGIN SELECT RAISE(ABORT,'FAKE PRIVATE SQLITE FAILURE'); END""")
        with self.assertRaises(StorageError) as failure:
            self.journal.applied(rows)
        self.assertNotIn("FAKE PRIVATE", str(failure.exception))
        self.assertEqual(self.journal.pending("one"), rows)
        with self.journal.db() as db:
            db.execute("DROP TRIGGER fail_ack")
        self.assertEqual(self.journal.applied(rows), 2)

    def test_validation_rejects_query_payloads_wrong_kinds_and_bad_dates(self):
        for args in [("../other", ["a"], "recall"), ("one", "a", "recall"),
                     ("one", ["a"], "query"), ("one", ["a|b"], "mention"),
                     ("one", [{"query": "NO_QUERY_ACCEPTED"}], "recall")]:
            with self.subTest(args=args), self.assertRaises(ValidationError):
                self.journal.enqueue(*args)
        for at in (-1, float("nan"), float("inf"), True, "2026-10-30"):
            with self.subTest(at=at), self.assertRaises(ValidationError):
                self.journal.enqueue("one", ["a"], "recall", at=at)
        self.assertEqual(self.journal.pending("one"), [])


if __name__ == "__main__":
    unittest.main()
