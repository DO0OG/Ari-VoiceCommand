import os
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QDialog

from core.custom_llm_providers import custom_api_key_name
from ui.settings_dialog import SettingsDialog
from ui.settings_llm_page import _LLMSettingsPage, _ValidatorThread, _valid_custom_base_url


PROVIDER_ID = "custom_0123456789abcdef0123456789abcdef"
PROVIDER = {
    "label": "Local test server",
    "base_url": "https://llm.example.test/v1",
    "default_model": "test-model",
}


class CustomLLMSettingsPageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication([])

    def _settings(self):
        return {
            "llm_provider": PROVIDER_ID,
            "llm_model": "",
            "llm_planner_provider": PROVIDER_ID,
            "llm_planner_model": "",
            "llm_execution_provider": PROVIDER_ID,
            "llm_execution_model": "",
            "custom_llm_providers": {PROVIDER_ID: dict(PROVIDER)},
            custom_api_key_name(PROVIDER_ID): "fake-api-key",
        }

    def test_get_values_round_trips_metadata_roles_and_separate_key(self):
        page = _LLMSettingsPage(self._settings())

        values = page.get_values()

        self.assertEqual(values["custom_llm_providers"], {PROVIDER_ID: PROVIDER})
        self.assertEqual(values[custom_api_key_name(PROVIDER_ID)], "fake-api-key")
        self.assertNotIn("api_key", values["custom_llm_providers"][PROVIDER_ID])
        self.assertEqual(values["llm_provider"], PROVIDER_ID)
        self.assertEqual(values["llm_planner_provider"], PROVIDER_ID)
        self.assertEqual(values["llm_execution_provider"], PROVIDER_ID)

    def test_delete_selected_provider_falls_back_and_clears_secret_and_models(self):
        page = _LLMSettingsPage(self._settings())
        page.llm_model_input.setText("main-override")
        page.llm_planner_model_input.setText("planner-override")
        page.llm_execution_model_input.setText("execution-override")

        page._remove_custom_provider(PROVIDER_ID)
        values = page.get_values()

        self.assertEqual(values["custom_llm_providers"], {})
        self.assertEqual(values["llm_provider"], "groq")
        self.assertEqual(values["llm_model"], "")
        # 역할 제공자는 "기본 제공자와 동일"로 돌아간다.
        self.assertEqual(values["llm_planner_provider"], "")
        self.assertEqual(values["llm_planner_model"], "")
        self.assertEqual(values["llm_execution_provider"], "")
        self.assertEqual(values["llm_execution_model"], "")
        self.assertEqual(values[custom_api_key_name(PROVIDER_ID)], "")

    def test_optional_key_custom_validation_uses_unsaved_configuration(self):
        page = _LLMSettingsPage({
            "custom_llm_providers": {PROVIDER_ID: dict(PROVIDER)},
            custom_api_key_name(PROVIDER_ID): "",
        })
        self.addCleanup(page.cleanup_threads)
        fake_thread = Mock()
        fake_thread.done = Mock()
        fake_thread.finished = Mock()
        fake_thread.isRunning.return_value = False
        with patch("ui.settings_llm_page._ValidatorThread", return_value=fake_thread) as thread_type:
            page._run_validation(PROVIDER_ID)

        thread_type.assert_called_once_with(
            PROVIDER_ID,
            "",
            "test-model",
            base_url=PROVIDER["base_url"],
            custom=True,
        )
        fake_thread.start.assert_called_once_with()
        self.assertNotIn("API Key를 입력하세요", page._validate_labels[PROVIDER_ID].text())

    def test_custom_provider_url_uses_shared_validation_rules(self):
        self.assertTrue(_valid_custom_base_url("https://host.example/v1"))
        for url in (
            "ftp://host.example/v1",
            "https://user:pass@host.example/v1",
            "https://host.example/v1?token=secret",
            "https://host.example/v1#fragment",
            "https://host.example/v1?",
            "https://host.example/v1#",
        ):
            with self.subTest(url=url):
                self.assertFalse(_valid_custom_base_url(url))

    def test_add_and_edit_custom_provider_keeps_model_and_key_in_round_trip(self):
        page = _LLMSettingsPage({})
        with patch("ui.settings_llm_page._CustomProviderDialog") as dialog_type:
            dialog = dialog_type.return_value
            dialog.exec.return_value = QDialog.DialogCode.Accepted
            dialog.get_values.return_value = {
                "label": "New server",
                "base_url": "https://new.example.test/v1",
            }
            page._add_custom_provider()

        provider_id = next(iter(page._custom_providers))
        page._llm_key_inputs[provider_id].setText("fake-api-key")
        page._llm_model_inputs[provider_id].setText("new-model")
        combo_index = page.llm_provider_combo.findData(provider_id)
        self.assertGreaterEqual(combo_index, 0)
        self.assertEqual(page.llm_provider_combo.itemText(combo_index), "New server")

        with patch("ui.settings_llm_page._CustomProviderDialog") as dialog_type:
            dialog = dialog_type.return_value
            dialog.exec.return_value = QDialog.DialogCode.Accepted
            dialog.get_values.return_value = {
                "label": "Renamed server",
                "base_url": "https://renamed.example.test/v1",
            }
            page._edit_custom_provider(provider_id)

        values = page.get_values()
        self.assertEqual(values["custom_llm_providers"][provider_id], {
            "label": "Renamed server",
            "base_url": "https://renamed.example.test/v1",
            "default_model": "new-model",
        })
        self.assertEqual(values[custom_api_key_name(provider_id)], "fake-api-key")
        self.assertEqual(page.llm_provider_combo.itemText(page.llm_provider_combo.findData(provider_id)), "Renamed server")

    def test_custom_validation_uses_sdk_config_and_hides_raw_failure(self):
        failure = "request failed with fake-api-key"
        create = Mock(side_effect=RuntimeError(failure))
        client = SimpleNamespace(
            chat=SimpleNamespace(completions=SimpleNamespace(create=create)),
        )
        openai_module = SimpleNamespace(OpenAI=Mock(return_value=client))
        messages = []
        thread = _ValidatorThread(
            PROVIDER_ID,
            "fake-api-key",
            "test-model",
            base_url=PROVIDER["base_url"],
            custom=True,
        )
        thread.done.connect(lambda success, message: messages.append((success, message)))

        with patch("ui.settings_llm_page.importlib.import_module", return_value=openai_module):
            thread.run()

        openai_module.OpenAI.assert_called_once_with(
            api_key="fake-api-key",
            timeout=10,
            max_retries=0,
            base_url=PROVIDER["base_url"],
        )
        self.assertEqual(messages[0][0], False)
        self.assertNotIn("fake-api-key", messages[0][1])
        self.assertNotIn(failure, messages[0][1])

    def test_custom_metadata_and_secret_changes_trigger_llm_reset(self):
        keys = {
            "custom_llm_providers",
            custom_api_key_name(PROVIDER_ID),
        }
        for key in keys:
            with self.subTest(key=key):
                dialog = SimpleNamespace(
                    changed_keys={key},
                    LLM_KEYS=SettingsDialog.LLM_KEYS,
                )
                self.assertTrue(SettingsDialog.llm_settings_changed(dialog))


if __name__ == "__main__":
    unittest.main()
