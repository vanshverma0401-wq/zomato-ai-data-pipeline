import importlib.util
import sys
import unittest
from contextlib import nullcontext
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock, patch


BLOCKED = {"allowed": False, "message": "Live AI is locked. Confirm usable free credits first.", "remaining_micro_usd": 0}
ALLOWED = {"allowed": True, "message": "Live AI is armed within the confirmed allowance.", "remaining_micro_usd": 100000}


class FakeLiveAccessError(RuntimeError):
    pass


class SessionState(dict):
    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError as error:
            raise AttributeError(name) from error

    def __setattr__(self, name, value):
        self[name] = value


class FakeStreamlit(ModuleType):
    def __init__(self, question="", clicked=()):
        super().__init__("streamlit")
        self.question = question
        self.clicked = set(clicked)
        self.session_state = SessionState()
        self.sidebar = nullcontext()
        self.buttons = {}
        self.warnings = []
        self.captions = []
        self.errors = []

    def title(self, value):
        pass

    def caption(self, value):
        self.captions.append(value)

    def warning(self, value):
        self.warnings.append(value)

    def error(self, value):
        self.errors.append(value)

    def subheader(self, value):
        pass

    def write(self, value):
        pass

    def code(self, value, language=None):
        pass

    def text_input(self, label, key=None, max_chars=None):
        self.session_state[key] = self.question
        return self.question

    def button(self, label, disabled=False):
        self.buttons[label] = disabled
        return label in self.clicked

    def spinner(self, value):
        return nullcontext()


def load_sql_app(streamlit, statuses):
    common = ModuleType("ai.common")
    common.LiveAccessError = FakeLiveAccessError
    common.live_access_status = Mock(side_effect=statuses)
    common.get_connection = Mock(side_effect=AssertionError("No real connection is allowed."))
    common.get_provider = Mock(side_effect=AssertionError("No real provider is allowed."))
    fake_pandas = ModuleType("pandas")
    path = Path(__file__).resolve().parents[2] / "ai" / "text_to_sql.py"
    spec = importlib.util.spec_from_file_location("_sql_credit_app_test", path)
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, {"streamlit": streamlit, "pandas": fake_pandas, "ai.common": common}):
        spec.loader.exec_module(module)
    return module, common


class SQLCreditUITests(unittest.TestCase):
    def test_blocked_initial_page_warns_and_disables_generation_without_live_access(self):
        streamlit = FakeStreamlit("Show orders")
        module, common = load_sql_app(streamlit, [BLOCKED])
        module.describe_allowed_marts = Mock(side_effect=AssertionError("Metadata must stay untouched."))
        module.render_page()
        self.assertEqual(streamlit.warnings, [BLOCKED["message"]])
        self.assertTrue(streamlit.buttons["Generate SQL"])
        module.describe_allowed_marts.assert_not_called()
        common.get_connection.assert_not_called()
        common.get_provider.assert_not_called()

    def test_stale_generate_event_cannot_bypass_a_blocked_status(self):
        streamlit = FakeStreamlit("Show orders", clicked=["Generate SQL"])
        module, common = load_sql_app(streamlit, [BLOCKED, BLOCKED])
        module.describe_allowed_marts = Mock(side_effect=AssertionError("Metadata must stay untouched."))
        module.render_page()
        self.assertEqual(streamlit.errors, [BLOCKED["message"]])
        module.describe_allowed_marts.assert_not_called()
        common.get_provider.assert_not_called()

    def test_credit_status_is_checked_again_before_metadata_or_generation(self):
        streamlit = FakeStreamlit("Show orders", clicked=["Generate SQL"])
        module, common = load_sql_app(streamlit, [ALLOWED, BLOCKED])
        module.describe_allowed_marts = Mock(side_effect=AssertionError("Metadata must stay untouched."))
        module.render_page()
        self.assertFalse(streamlit.buttons["Generate SQL"])
        self.assertEqual(streamlit.errors, [BLOCKED["message"]])
        self.assertEqual(common.live_access_status.call_count, 2)
        module.describe_allowed_marts.assert_not_called()
        common.get_provider.assert_not_called()

    def test_provider_credit_errors_show_the_controlled_message(self):
        streamlit = FakeStreamlit("Show orders", clicked=["Generate SQL"])
        module, common = load_sql_app(streamlit, [ALLOWED, ALLOWED])
        module.describe_allowed_marts = Mock(return_value="FCT_ORDERS(ORDER_ID NUMBER)")
        common.get_provider = Mock(return_value=object())
        module.get_provider = common.get_provider
        module.generate_approved_query = Mock(side_effect=FakeLiveAccessError("The free-credit confirmation expired."))
        module.render_page()
        self.assertEqual(streamlit.errors, ["The free-credit confirmation expired."])
        self.assertNotIn("sql_approval", streamlit.session_state)

    def test_generation_does_not_run_the_generated_query(self):
        streamlit = FakeStreamlit("Show orders", clicked=["Generate SQL"])
        module, common = load_sql_app(streamlit, [ALLOWED, ALLOWED])
        module.describe_allowed_marts = Mock(return_value="FCT_ORDERS(ORDER_ID NUMBER)")
        module.get_provider = Mock(return_value=object())
        approved = SimpleNamespace(question="Show orders", sql="SELECT ORDER_ID FROM ZOMATO.MARTS.FCT_ORDERS LIMIT 100", tables=("FCT_ORDERS",))
        module.generate_approved_query = Mock(return_value=approved)
        module.execute_approved_query = Mock(side_effect=AssertionError("Execution requires its own button."))
        module.render_page()
        self.assertIs(streamlit.session_state.sql_approval, approved)
        self.assertFalse(streamlit.buttons["Run query"])
        module.execute_approved_query.assert_not_called()
        common.get_connection.assert_not_called()

    def test_existing_approved_query_can_run_without_model_credit(self):
        streamlit = FakeStreamlit("Show orders", clicked=["Run query"])
        approved = SimpleNamespace(question="Show orders", sql="SELECT ORDER_ID FROM ZOMATO.MARTS.FCT_ORDERS LIMIT 100", tables=("FCT_ORDERS",))
        streamlit.session_state.sql_session_id = "session-a"
        streamlit.session_state.sql_approval = approved
        module, common = load_sql_app(streamlit, [BLOCKED])
        module.execute_approved_query = Mock(return_value=None)
        module.render_page()
        self.assertFalse(streamlit.buttons["Run query"])
        module.execute_approved_query.assert_called_once_with(approved, "Show orders", "session-a", common.get_connection)
        common.get_provider.assert_not_called()


if __name__ == "__main__":
    unittest.main()
