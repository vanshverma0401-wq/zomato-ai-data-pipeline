import importlib.util
import io
import json
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock, patch


class FakeLiveAccessError(RuntimeError):
    pass


def load_preflight(allowed=False, arm_error=None):
    common = ModuleType("ai.common")
    common.LiveAccessError = FakeLiveAccessError
    common.load_settings = Mock(return_value=SimpleNamespace(
        api_key="sk-example-only-not-real",
        state_path=Path("/unused-test-state"),
        chat_model="test-chat-model",
        embedding_model="test-embedding-model",
        sample_n=5,
        rag_sample_n=100,
    ))
    ledger = SimpleNamespace(
        arm=Mock(side_effect=arm_error),
        status=Mock(return_value={"reserved_micro_usd": 0, "limit_micro_usd": 100000, "credit_confirmation": None}),
        reserve=Mock(side_effect=AssertionError("Preflight must not reserve requests.")),
    )
    common.BudgetLedger = Mock(return_value=ledger)
    common.live_access_status = Mock(return_value={
        "allowed": allowed,
        "message": "Live AI is armed." if allowed else "The free-credit confirmation is missing or expired.",
        "remaining_micro_usd": 100000,
    })
    common.get_connection = Mock(side_effect=AssertionError("No database connection is allowed."))
    common.get_provider = Mock(side_effect=AssertionError("No provider is allowed."))
    path = Path(__file__).resolve().parents[2] / "ai" / "preflight.py"
    spec = importlib.util.spec_from_file_location("_preflight_test", path)
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, {"ai.common": common}):
        spec.loader.exec_module(module)
    return module, common, ledger


def run_main(module, args):
    output = io.StringIO()
    errors = io.StringIO()
    with patch.object(sys, "argv", ["ai.preflight"] + args), redirect_stdout(output), redirect_stderr(errors):
        module.main()
    return output.getvalue(), errors.getvalue()


class PreflightTests(unittest.TestCase):
    def test_status_reports_the_effective_block_without_live_access_or_key_disclosure(self):
        module, common, ledger = load_preflight()
        output, errors = run_main(module, [])
        status = json.loads(output)
        self.assertFalse(status["live_access"]["allowed"])
        self.assertIn("missing or expired", status["live_access"]["message"])
        self.assertEqual(status["live_access"]["remaining_micro_usd"], 100000)
        self.assertTrue(status["api_key_present"])
        self.assertNotIn(common.load_settings.return_value.api_key, output)
        self.assertEqual(errors, "")
        ledger.arm.assert_not_called()
        ledger.reserve.assert_not_called()
        common.get_connection.assert_not_called()
        common.get_provider.assert_not_called()

    def test_status_reports_allowed_without_reserving_a_request(self):
        module, common, ledger = load_preflight(allowed=True)
        output, _ = run_main(module, [])
        self.assertTrue(json.loads(output)["live_access"]["allowed"])
        common.live_access_status.assert_called_once_with()
        ledger.reserve.assert_not_called()

    def test_confirmation_delegates_the_observed_balance_and_explicit_policy(self):
        module, common, ledger = load_preflight(allowed=True)
        output, errors = run_main(module, ["--confirm-free-credits", "--free-credit-usd", "0.25", "--no-paid-fallback"])
        ledger.arm.assert_called_once_with(free_credit_usd=0.25, no_paid_fallback=True)
        self.assertTrue(json.loads(output)["live_access"]["allowed"])
        self.assertEqual(errors, "")
        ledger.reserve.assert_not_called()
        common.get_provider.assert_not_called()

    def test_missing_balance_is_a_concise_argument_error(self):
        module, common, ledger = load_preflight()
        errors = io.StringIO()
        with patch.object(sys, "argv", ["ai.preflight", "--confirm-free-credits"]), redirect_stderr(errors), self.assertRaises(SystemExit) as raised:
            module.main()
        self.assertEqual(raised.exception.code, 2)
        self.assertIn("--free-credit-usd", errors.getvalue())
        self.assertNotIn("Traceback", errors.getvalue())
        ledger.arm.assert_not_called()
        common.live_access_status.assert_not_called()

    def test_rejected_confirmation_is_an_argument_error_instead_of_a_traceback(self):
        module, common, ledger = load_preflight(arm_error=FakeLiveAccessError("The recorded promotion expired."))
        errors = io.StringIO()
        args = ["ai.preflight", "--confirm-free-credits", "--free-credit-usd", "0.25", "--no-paid-fallback"]
        with patch.object(sys, "argv", args), redirect_stderr(errors), self.assertRaises(SystemExit) as raised:
            module.main()
        self.assertEqual(raised.exception.code, 2)
        self.assertIn("The recorded promotion expired.", errors.getvalue())
        self.assertNotIn("Traceback", errors.getvalue())
        common.live_access_status.assert_not_called()
        ledger.reserve.assert_not_called()

    def test_missing_no_paid_fallback_flag_is_not_overridden(self):
        module, common, ledger = load_preflight(arm_error=FakeLiveAccessError("Confirm no paid fallback first."))
        errors = io.StringIO()
        args = ["ai.preflight", "--confirm-free-credits", "--free-credit-usd", "0.25"]
        with patch.object(sys, "argv", args), redirect_stderr(errors), self.assertRaises(SystemExit):
            module.main()
        ledger.arm.assert_called_once_with(free_credit_usd=0.25, no_paid_fallback=False)
        self.assertIn("Confirm no paid fallback first.", errors.getvalue())
        common.get_connection.assert_not_called()


if __name__ == "__main__":
    unittest.main()
