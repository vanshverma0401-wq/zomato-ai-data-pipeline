import json
import importlib
import multiprocessing
import tempfile
import unittest
from pathlib import Path

from ai.rag import INSUFFICIENT_CONTEXT, answer_question, build_index, load_index


class FakeCursor:
    def __init__(self, rows):
        self.rows = rows
        self.query = None
        self.closed = False

    def execute(self, query):
        self.query = query
        return self

    def fetchmany(self, count):
        return self.rows[:count]

    def close(self):
        self.closed = True


class FakeConnection:
    def __init__(self, rows):
        self.result = FakeCursor(rows)

    def cursor(self):
        return self.result


class FakeProvider:
    def __init__(self, response=None):
        self.embedded = []
        self.completed = []
        self.response = response or {
            "answer": "Delivery was late [101].",
            "citations": ["101"],
            "sufficient_context": True,
        }

    def embed(self, texts):
        self.embedded.append(list(texts))
        return [[1.0, 0.0] if "late" in text.lower() else [0.0, 1.0] for text in texts]

    def complete(self, system, user, schema=None):
        self.completed.append((system, user, schema))
        return json.dumps(self.response)


def hold_refresh(rows, cache_path, ready, release, outcomes):
    provider = FakeProvider()
    embed = provider.embed

    def wait_for_release(texts):
        ready.set()
        if not release.wait(10):
            raise RuntimeError("The test refresh was not released.")
        return embed(texts)

    provider.embed = wait_for_release
    try:
        build_index(FakeConnection(rows), provider, cache_path)
        outcomes.put("ok")
    except Exception as error:
        outcomes.put(type(error).__name__)


class RagTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.cache = Path(self.temp.name) / "reviews.sqlite3"
        self.rows = [
            (101, "Delhi", 1, "Delivery was late"),
            (102, "Mumbai", 5, "The food was excellent"),
        ]

    def tearDown(self):
        self.temp.cleanup()

    def test_loading_absent_index_does_not_create_cache(self):
        self.assertIsNone(load_index(self.cache))
        self.assertFalse(self.cache.exists())

    def test_refresh_reuses_persistent_embeddings_and_reembeds_changed_comment(self):
        first = FakeProvider()
        build_index(FakeConnection(self.rows), first, self.cache, sample_n=2)
        self.assertEqual(len(first.embedded[0]), 2)
        restored = load_index(self.cache, sample_n=2)
        self.assertEqual([review.review_id for review in restored.reviews], ["101", "102"])
        second = FakeProvider()
        build_index(FakeConnection(self.rows), second, self.cache, sample_n=2)
        self.assertEqual(second.embedded, [])
        changed = [(101, "Delhi", 1, "Delivery was very late"), self.rows[1]]
        build_index(FakeConnection(changed), second, self.cache, sample_n=2)
        self.assertEqual(second.embedded, [["Delivery was very late"]])

    def test_sample_is_bounded_deterministic_and_cursor_closed(self):
        connection = FakeConnection(self.rows)
        index = build_index(connection, FakeProvider(), self.cache, sample_n=1)
        self.assertEqual(len(index.reviews), 1)
        self.assertIn("STAGING.STG_REVIEWS", connection.result.query)
        self.assertIn("ORDER BY REVIEW_ID", connection.result.query)
        self.assertIn("LIMIT 1", connection.result.query)
        self.assertTrue(connection.result.closed)

    def test_limits_and_embedding_model_rejected_before_external_calls(self):
        provider = FakeProvider()
        for sample_n in (0, 501):
            with self.assertRaises(ValueError):
                build_index(FakeConnection(self.rows), provider, self.cache, sample_n=sample_n)
        with self.assertRaises(ValueError):
            build_index(FakeConnection(self.rows), provider, self.cache, embedding_model="local-model")
        self.assertEqual(provider.embedded, [])

    def test_empty_corpus_answers_without_provider_calls(self):
        provider = FakeProvider()
        index = build_index(FakeConnection([]), provider, self.cache)
        result = answer_question("How was delivery?", index, provider)
        self.assertEqual(result["answer"], INSUFFICIENT_CONTEXT)
        self.assertFalse(result["sufficient_context"])
        self.assertEqual(provider.embedded, [])
        self.assertEqual(provider.completed, [])

    def test_retrieval_ranks_question_embedding_and_preserves_real_citations(self):
        provider = FakeProvider()
        index = build_index(FakeConnection(self.rows), provider, self.cache)
        result = answer_question("Was delivery late?", index, provider)
        self.assertEqual(result["citations"], ["101"])
        self.assertEqual(result["sources"][0]["review_id"], "101")
        self.assertAlmostEqual(result["sources"][0]["similarity"], 1.0)
        self.assertEqual(provider.embedded[-1], ["Was delivery late?"])
        self.assertIn("untrusted", provider.completed[0][0].lower())
        self.assertIn('"review_id": "101"', provider.completed[0][1])

    def test_invented_or_missing_or_mismatched_citation_fails_closed(self):
        index = build_index(FakeConnection(self.rows), FakeProvider(), self.cache)
        responses = [
            {"answer": "Late [999].", "citations": ["999"], "sufficient_context": True},
            {"answer": "Late.", "citations": [], "sufficient_context": True},
            {"answer": "Late.", "citations": ["101"], "sufficient_context": True},
            {"answer": "Late [102].", "citations": ["101"], "sufficient_context": True},
        ]
        for response in responses:
            with self.subTest(response=response), self.assertRaises(ValueError):
                answer_question("Was delivery late?", index, FakeProvider(response))

    def test_model_insufficient_context_cannot_display_uncited_claim(self):
        index = build_index(FakeConnection(self.rows), FakeProvider(), self.cache)
        provider = FakeProvider({"answer": "An unsupported claim", "citations": [], "sufficient_context": False})
        result = answer_question("What happened elsewhere?", index, provider)
        self.assertEqual(result["answer"], INSUFFICIENT_CONTEXT)
        self.assertEqual(result["citations"], [])

    def test_question_and_malformed_vector_limits_fail_before_generation(self):
        provider = FakeProvider()
        index = build_index(FakeConnection(self.rows), provider, self.cache)
        before = len(provider.embedded)
        for question in (" ", "x" * 1001):
            with self.assertRaises(ValueError):
                answer_question(question, index, provider)
        self.assertEqual(len(provider.embedded), before)
        provider.embed = lambda texts: [[float("nan"), 0.0]]
        with self.assertRaises(ValueError):
            answer_question("Delivery?", index, provider)
        self.assertEqual(provider.completed, [])

    def test_bad_embedding_batch_does_not_publish_index(self):
        provider = FakeProvider()
        provider.embed = lambda texts: [[1.0, 0.0]]
        with self.assertRaises(ValueError):
            build_index(FakeConnection(self.rows), provider, self.cache)
        self.assertIsNone(load_index(self.cache))

    def test_paid_batches_survive_later_failure_without_publishing_partial_corpus(self):
        rows = [(number, "Delhi", 1, f"Late delivery {number}") for number in range(21)]
        provider = FakeProvider()
        embed = provider.embed

        def fail_second_batch(texts):
            if provider.embedded:
                raise RuntimeError("Allowance exhausted")
            return embed(texts)

        provider.embed = fail_second_batch
        with self.assertRaises(RuntimeError):
            build_index(FakeConnection(rows), provider, self.cache)
        self.assertIsNone(load_index(self.cache))
        retry = FakeProvider()
        build_index(FakeConnection(rows), retry, self.cache)
        self.assertEqual(retry.embedded, [["Late delivery 20"]])

    def test_retrieval_never_exposes_more_than_five_sources(self):
        rows = [(number, "Delhi", 1, f"Late delivery {number}") for number in range(101, 108)]
        index = build_index(FakeConnection(rows), FakeProvider(), self.cache)
        result = answer_question("Was delivery late?", index, FakeProvider())
        self.assertEqual(len(result["sources"]), 5)

    def test_ui_module_import_needs_no_streamlit_or_common_or_network(self):
        module = importlib.import_module("ai.rag_chat")
        self.assertTrue(callable(module.main))

    def test_cross_process_refresh_blocks_duplicate_embedding_and_keeps_previous_index_readable(self):
        build_index(FakeConnection(self.rows), FakeProvider(), self.cache)
        changed = [(101, "Delhi", 1, "Delivery was very late"), self.rows[1]]
        context = multiprocessing.get_context("spawn")
        ready = context.Event()
        release = context.Event()
        outcomes = context.Queue()
        worker = context.Process(target=hold_refresh, args=(changed, self.cache, ready, release, outcomes))
        worker.start()
        try:
            self.assertTrue(ready.wait(10), "The separate process never reached its embedding request.")
            previous = load_index(self.cache)
            self.assertEqual(previous.reviews[0].comment, "Delivery was late")
            provider = FakeProvider()
            connection = FakeConnection(changed)
            with self.assertRaisesRegex(RuntimeError, "refresh.*progress"):
                build_index(connection, provider, self.cache)
            self.assertEqual(provider.embedded, [])
            self.assertIsNone(connection.result.query)
        finally:
            release.set()
            worker.join(10)
            if worker.is_alive():
                worker.terminate()
                worker.join(5)
        self.assertEqual(worker.exitcode, 0)
        self.assertEqual(outcomes.get(timeout=2), "ok")
        outcomes.close()
        retry = FakeProvider()
        refreshed = build_index(FakeConnection(changed), retry, self.cache)
        self.assertEqual(retry.embedded, [])
        self.assertEqual(refreshed.reviews[0].comment, "Delivery was very late")


if __name__ == "__main__":
    unittest.main()
