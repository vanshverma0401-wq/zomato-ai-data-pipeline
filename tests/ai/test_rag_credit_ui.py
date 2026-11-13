import sys
import tempfile
import types
import unittest
from contextlib import nullcontext
from pathlib import Path
from unittest.mock import patch

from ai import common, rag_chat


class RagCreditUITests(unittest.TestCase):
    def render_locked(self, *, stale_build=False, stale_ask=False, cached_index=None):
        ui = types.ModuleType("streamlit")
        ui.session_state = {}
        ui.warnings = []
        ui.buttons = {}
        ui.set_page_config = ui.title = ui.caption = ui.info = ui.error = lambda *a, **k: None
        ui.warning = ui.warnings.append
        ui.spinner = ui.form = lambda *a, **k: nullcontext()
        def button(label, **kwargs):
            ui.buttons[label] = kwargs.get("disabled", False)
            return stale_build
        def submit(label, **kwargs):
            ui.buttons[label] = kwargs.get("disabled", False)
            return stale_ask
        ui.button = button
        ui.form_submit_button = submit
        ui.text_area = lambda *a, **k: "What do these reviews say?"
        external_calls = []
        def forbidden(*args, **kwargs):
            external_calls.append((args, kwargs))
            raise AssertionError("External work must not start while credit access is locked.")
        with tempfile.TemporaryDirectory() as folder:
            settings = common.Settings(state_path=Path(folder))
            status = {"allowed": False, "message": "Live AI is locked. Complete the free-credit check first.", "remaining_micro_usd": 0}
            with patch.dict(sys.modules, {"streamlit": ui}), patch.multiple(common, load_settings=lambda: settings, live_access_status=lambda *a, **k: status, state_dir=lambda: Path(folder), get_provider=forbidden, get_connection=forbidden), patch("ai.rag.load_index", return_value=cached_index):
                rag_chat.main()
        self.assertEqual(external_calls, [])
        self.assertIn(status["message"], ui.warnings)
        return ui

    def test_locked_page_explains_reason_and_disables_index_refresh(self):
        ui = self.render_locked()
        self.assertTrue(ui.buttons["Build / refresh review index"])

    def test_stale_refresh_event_cannot_query_warehouse_or_construct_provider(self):
        self.render_locked(stale_build=True)

    def test_stale_question_event_cannot_call_model_with_cached_index(self):
        index = types.SimpleNamespace(reviews=(object(),), refreshed_at="saved")
        ui = self.render_locked(stale_ask=True, cached_index=index)
        self.assertTrue(ui.buttons["Ask using retrieved reviews"])


if __name__ == "__main__":
    unittest.main()
