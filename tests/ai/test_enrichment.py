import json
import multiprocessing
import tempfile
import unittest
from pathlib import Path

from ai.enrichment import run_enrichment, validate_classification


LABELS = {
    "sentiment_label": "negative",
    "sentiment_score": -0.8,
    "topic": "delivery",
    "key_issue": "Food arrived late",
}


class FakeProvider:
    def __init__(self, payload=None):
        self.payload = LABELS if payload is None else payload
        self.calls = 0

    def complete(self, system, user, schema=None):
        self.calls += 1
        return json.dumps(self.payload)


class FakeCursor:
    def __init__(self, connection):
        self.connection = connection

    def execute(self, sql, parameters=None):
        self.connection.statements.append((sql, parameters))
        if sql.lstrip().startswith("SELECT r.REVIEW_ID") and hasattr(self.connection, "selection_event"):
            self.connection.selection_event.set()
        if sql.lstrip().startswith("MERGE"):
            self.connection.merges += 1
            if self.connection.fail_save:
                raise RuntimeError("warehouse temporarily unavailable")
        return self

    def fetchall(self):
        return self.connection.reviews

    def close(self):
        self.connection.cursor_closed = True


class FakeConnection:
    def __init__(self, reviews=None, fail_save=False):
        self.reviews = [("r-1", "The food arrived after two hours.")] if reviews is None else reviews
        self.fail_save = fail_save
        self.statements = []
        self.merges = 0
        self.commits = 0
        self.cursor_closed = False

    def cursor(self):
        return FakeCursor(self)

    def commit(self):
        self.commits += 1


class SharedBlockingProvider:
    def __init__(self, calls, entered, release):
        self.calls = calls
        self.entered = entered
        self.release = release

    def complete(self, system, user, schema=None):
        with self.calls.get_lock():
            self.calls.value += 1
        self.entered.set()
        if not self.release.wait(10):
            raise RuntimeError("test worker was not released")
        return json.dumps(LABELS)


def enrichment_worker(cache_dir, calls, entered, release, selected):
    connection = FakeConnection()
    connection.selection_event = selected
    provider = SharedBlockingProvider(calls, entered, release)
    run_enrichment(connection, provider, cache_dir=Path(cache_dir))


class EnrichmentTests(unittest.TestCase):
    def test_second_process_waits_before_selection_and_reuses_first_paid_response(self):
        context = multiprocessing.get_context("spawn")
        calls = context.Value("i", 0)
        first_entered = context.Event()
        second_entered = context.Event()
        release = context.Event()
        first_selected = context.Event()
        second_selected = context.Event()
        with tempfile.TemporaryDirectory() as folder:
            first = context.Process(target=enrichment_worker, args=(folder, calls, first_entered, release, first_selected))
            second = context.Process(target=enrichment_worker, args=(folder, calls, second_entered, release, second_selected))
            first.start()
            try:
                self.assertTrue(first_entered.wait(5))
                second.start()
                self.assertFalse(second_selected.wait(0.5))
            finally:
                release.set()
                first.join(5)
                if second.pid is not None:
                    second.join(5)
                for worker in (first, second):
                    if worker.pid is not None and worker.is_alive():
                        worker.terminate()
                        worker.join(5)
            self.assertEqual(first.exitcode, 0)
            self.assertEqual(second.exitcode, 0)
            self.assertTrue(second_selected.is_set())
            self.assertFalse(second_entered.is_set())
            self.assertEqual(calls.value, 1)

    def test_invalid_model_response_is_rejected_before_any_merge(self):
        with tempfile.TemporaryDirectory() as folder:
            conn = FakeConnection()
            provider = FakeProvider({**LABELS, "sentiment_score": 10})
            with self.assertRaises(ValueError):
                run_enrichment(conn, provider, cache_dir=Path(folder))
            self.assertEqual(conn.merges, 0)
            self.assertTrue(conn.cursor_closed)

    def test_retry_uses_cached_response_after_warehouse_save_failure(self):
        with tempfile.TemporaryDirectory() as folder:
            provider = FakeProvider()
            first = FakeConnection(fail_save=True)
            with self.assertRaises(RuntimeError):
                run_enrichment(first, provider, cache_dir=Path(folder))
            second = FakeConnection()
            result = run_enrichment(second, provider, cache_dir=Path(folder))
            self.assertEqual(provider.calls, 1)
            self.assertEqual(result["saved"], 1)
            self.assertEqual(second.commits, 1)

    def test_successful_reviews_are_committed_individually(self):
        with tempfile.TemporaryDirectory() as folder:
            conn = FakeConnection([("r-1", "Late delivery"), ("r-2", "Cold food")])
            result = run_enrichment(conn, FakeProvider(), cache_dir=Path(folder))
            self.assertEqual(result["saved"], 2)
            self.assertEqual(conn.commits, 2)

    def test_empty_source_does_not_request_a_model(self):
        with tempfile.TemporaryDirectory() as folder:
            provider = FakeProvider()
            result = run_enrichment(FakeConnection([]), provider, cache_dir=Path(folder))
            self.assertEqual(result["saved"], 0)
            self.assertEqual(provider.calls, 0)

    def test_oversized_sample_is_rejected_before_querying(self):
        conn = FakeConnection()
        with self.assertRaises(ValueError):
            run_enrichment(conn, FakeProvider(), sample_n=21, cache_dir=Path("unused"))
        self.assertEqual(conn.statements, [])

    def test_score_and_issue_constraints_are_validated(self):
        for change in (
            {"sentiment_score": True},
            {"sentiment_score": float("nan")},
            {"sentiment_label": "mixed"},
            {"topic": "unknown"},
            {"key_issue": "one two three four five six seven"},
            {"unexpected": "value"},
        ):
            with self.subTest(change=change):
                with self.assertRaises(ValueError):
                    validate_classification({**LABELS, **change})


if __name__ == "__main__":
    unittest.main()
