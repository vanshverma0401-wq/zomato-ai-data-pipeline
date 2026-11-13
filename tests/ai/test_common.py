import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from ai.common import BudgetLedger, LiveAccessError, Provider, Settings


class CommonTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        environment = patch.dict(os.environ, {
            "OPENAI_ORGANIZATION_ID": "org-unit-test",
            "OPENAI_PROJECT_ID": "proj_unit_test",
            "OPENAI_CREDIT_EXPIRES_AT": "2030-01-05T00:00:00+00:00",
        })
        environment.start()
        self.addCleanup(environment.stop)
        self.now = datetime(2030, 1, 1, tzinfo=timezone.utc)
        self.settings = Settings(api_key="sk-test-do-not-display", state_path=self.root)

    def arm(self, ledger, **kwargs):
        ledger.arm(free_credit_usd=1, no_paid_fallback=True, now=self.now, **kwargs)

    def test_unconfirmed_credits_block_before_transport(self):
        calls = []
        provider = Provider(self.settings, transport=lambda *a: calls.append(a), now=lambda: self.now)
        with self.assertRaises(LiveAccessError):
            provider.complete("system", "question")
        self.assertEqual(calls, [])

    def test_expired_credit_confirmation_cannot_be_extended_by_rearming(self):
        ledger = BudgetLedger(self.root)
        with self.assertRaises(LiveAccessError):
            ledger.arm(free_credit_usd=40, no_paid_fallback=True, now=datetime(2030, 1, 6, tzinfo=timezone.utc))

    def test_paid_fallback_is_rejected(self):
        with self.assertRaises(LiveAccessError):
            BudgetLedger(self.root).arm(free_credit_usd=1, no_paid_fallback=False, now=self.now)

    def test_reservations_survive_reopening_and_rearming(self):
        ledger = BudgetLedger(self.root)
        self.arm(ledger)
        ledger.reserve(60000, now=self.now)
        fresh = BudgetLedger(self.root)
        self.arm(fresh)
        with self.assertRaises(LiveAccessError):
            fresh.reserve(60000, now=self.now)
        self.assertEqual(fresh.status()["reserved_micro_usd"], 60000)

    def test_credit_confirmation_expires_after_one_day(self):
        ledger = BudgetLedger(self.root)
        self.arm(ledger)
        with self.assertRaises(LiveAccessError):
            ledger.reserve(1, now=self.now + timedelta(days=1, seconds=1))

    def test_request_is_bound_to_selected_org_project_and_validated(self):
        ledger = BudgetLedger(self.root)
        self.arm(ledger)
        captured = []
        def transport(endpoint, payload, headers):
            captured.append((endpoint, payload, headers))
            return {"choices": [{"finish_reason": "stop", "message": {"content": '{"answer":"ok"}'}}]}
        schema = {"type": "object", "properties": {"answer": {"type": "string"}}, "required": ["answer"], "additionalProperties": False}
        provider = Provider(self.settings, transport=transport, now=lambda: self.now)
        self.assertEqual(json.loads(provider.complete("system", "question", schema)), {"answer": "ok"})
        self.assertEqual(captured[0][2]["OpenAI-Project"], self.settings.project_id)
        self.assertEqual(captured[0][1]["response_format"]["type"], "json_schema")
        self.assertFalse(captured[0][1]["store"])

    def test_provider_errors_never_echo_sensitive_response(self):
        ledger = BudgetLedger(self.root)
        self.arm(ledger)
        def broken(*args):
            raise RuntimeError("sk-test-do-not-display")
        provider = Provider(self.settings, transport=broken, now=lambda: self.now)
        with self.assertRaisesRegex(RuntimeError, "OpenAI request failed") as caught:
            provider.complete("system", "question")
        self.assertNotIn("sk-test", str(caught.exception))

    def test_malformed_embedding_response_is_rejected(self):
        ledger = BudgetLedger(self.root)
        self.arm(ledger)
        provider = Provider(self.settings, transport=lambda *a: {"data": [{"index": 0, "embedding": [float('nan')]}]}, now=lambda: self.now)
        with self.assertRaises(ValueError):
            provider.embed(["review"])

    def test_structured_response_must_match_schema_before_return(self):
        self.arm(BudgetLedger(self.root))
        response = {"choices": [{"finish_reason": "stop", "message": {"content": '{"answer":42}'}}]}
        provider = Provider(self.settings, transport=lambda *a: response, now=lambda: self.now)
        schema = {"type": "object", "properties": {"answer": {"type": "string"}}, "required": ["answer"], "additionalProperties": False}
        with self.assertRaisesRegex(ValueError, "incomplete or invalid"):
            provider.complete("system", "question", schema)

    def test_parallel_reservations_cannot_overrun_the_total_allowance(self):
        from concurrent.futures import ThreadPoolExecutor
        self.arm(BudgetLedger(self.root))
        def reserve(_):
            try:
                BudgetLedger(self.root).reserve(10000, now=self.now)
                return True
            except LiveAccessError:
                return False
        with ThreadPoolExecutor(max_workers=6) as pool:
            accepted = list(pool.map(reserve, range(15)))
        self.assertEqual(sum(accepted), 10)
        self.assertEqual(BudgetLedger(self.root).status()["reserved_micro_usd"], 100000)

    def test_live_status_explains_missing_confirmation_without_reserving(self):
        from ai.common import live_access_status
        status = live_access_status(self.settings, now=self.now)
        self.assertFalse(status["allowed"])
        self.assertIn("free-credit", status["message"])
        self.assertEqual(BudgetLedger(self.root).status()["reserved_micro_usd"], 0)

    def test_live_status_is_read_only_when_confirmation_is_valid(self):
        from ai.common import live_access_status
        self.arm(BudgetLedger(self.root))
        status = live_access_status(self.settings, now=self.now)
        self.assertTrue(status["allowed"])
        self.assertEqual(status["remaining_micro_usd"], 100000)
        self.assertEqual(BudgetLedger(self.root).status()["reserved_micro_usd"], 0)

    def test_live_status_reports_expired_confirmation_without_calling_provider(self):
        from ai.common import live_access_status
        self.arm(BudgetLedger(self.root))
        status = live_access_status(self.settings, now=self.now + timedelta(days=2))
        self.assertFalse(status["allowed"])
        self.assertIn("expired", status["message"])


if __name__ == "__main__":
    unittest.main()
