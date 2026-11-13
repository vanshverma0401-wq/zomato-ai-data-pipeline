import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from ai.common import BudgetLedger, LiveAccessError, Provider, Settings, load_settings


class PublicConfigTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name)
        self.now = datetime(2030, 1, 1, tzinfo=timezone.utc)
        environment = patch.dict(os.environ, {
            "OPENAI_ORGANIZATION_ID": "org-unit-test",
            "OPENAI_PROJECT_ID": "proj_unit_test",
            "OPENAI_CREDIT_EXPIRES_AT": "2030-01-05T00:00:00Z",
        })
        environment.start()
        self.addCleanup(environment.stop)

    def test_settings_read_current_environment_after_module_import(self):
        with patch("dotenv.load_dotenv"):
            settings = load_settings()
        self.assertEqual(settings.organization_id, "org-unit-test")
        self.assertEqual(settings.project_id, "proj_unit_test")

    def test_missing_expiry_fails_closed(self):
        with patch.dict(os.environ, {"OPENAI_CREDIT_EXPIRES_AT": ""}):
            with self.assertRaisesRegex(LiveAccessError, "expired"):
                BudgetLedger(self.path).arm(free_credit_usd=1, no_paid_fallback=True, now=self.now)

    def test_malformed_or_timezone_free_expiry_is_rejected(self):
        for value in ("not-a-date", "2030-01-05T00:00:00"):
            with self.subTest(value=value), patch.dict(os.environ, {"OPENAI_CREDIT_EXPIRES_AT": value}):
                with self.assertRaisesRegex(LiveAccessError, "timezone"):
                    BudgetLedger(self.path).arm(free_credit_usd=1, no_paid_fallback=True, now=self.now)

    def test_missing_identity_cannot_arm_live_requests(self):
        with patch.dict(os.environ, {"OPENAI_PROJECT_ID": ""}):
            with self.assertRaisesRegex(LiveAccessError, "OPENAI_PROJECT_ID"):
                BudgetLedger(self.path).arm(free_credit_usd=1, no_paid_fallback=True, now=self.now)

    def test_changing_project_invalidates_an_existing_receipt(self):
        ledger = BudgetLedger(self.path)
        ledger.arm(free_credit_usd=1, no_paid_fallback=True, now=self.now)
        with patch.dict(os.environ, {"OPENAI_PROJECT_ID": "proj_other_unit_test"}):
            with self.assertRaisesRegex(LiveAccessError, "different project"):
                ledger.reserve(1, now=self.now)

    def test_stale_provider_identity_is_blocked_before_transport(self):
        settings = Settings(api_key="sk-test-do-not-display", state_path=self.path, project_id="proj_stale_unit_test")
        calls = []
        provider = Provider(settings, transport=lambda *args: calls.append(args), now=lambda: self.now)
        with self.assertRaisesRegex(LiveAccessError, "do not match"):
            provider.embed(["review"])
        self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
