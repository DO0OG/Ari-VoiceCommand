import json
import unittest

from core.config_manager import ConfigManager
from core.custom_llm_providers import (
    custom_api_key_name,
    get_custom_providers,
    is_custom_secret_key,
    normalize_custom_provider_settings,
)
from core.secret_store import SecretStore
from tests.test_secret_store import _isolated_settings, _opaque_crypto, _read_json


_PROVIDER = "custom_0123456789abcdef0123456789abcdef"
_API_KEY = custom_api_key_name(_PROVIDER)
_METADATA = {"label": "Local", "base_url": "https://api.example.test/v1", "default_model": "model-x"}


class CustomLlmStorageTests(unittest.TestCase):
    def test_metadata_validation_whitelists_fields_and_falls_back_deleted_selection(self):
        metadata = {
            _PROVIDER: {**_METADATA, "api_key": "nested-secret", "extra": "ignored"},
            "custom_ABCDEF0123456789abcdef0123456789": _METADATA,
            "custom_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa": {**_METADATA, "base_url": "https://user:pass@example.test"},
            "custom_bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb": {**_METADATA, "base_url": "https://example.test/?key=secret"},
            "custom_cccccccccccccccccccccccccccccccc": {**_METADATA, "default_model": None},
        }
        providers = get_custom_providers({"custom_llm_providers": metadata})
        self.assertEqual(providers, {_PROVIDER: _METADATA})

        self.assertTrue(is_custom_secret_key(_API_KEY))
        self.assertFalse(is_custom_secret_key(_API_KEY.upper()))
        self.assertFalse(is_custom_secret_key("custom_short_api_key"))
        with self.assertRaises(ValueError):
            custom_api_key_name("custom_invalid")

        settings = {
            "custom_llm_providers": {_PROVIDER: _METADATA},
            "llm_provider": "custom_ffffffffffffffffffffffffffffffff",
            "llm_model": "missing-main-model",
            "llm_planner_provider": _PROVIDER,
            "llm_planner_model": "planner-model",
            "llm_execution_provider": "custom_eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee",
            "llm_execution_model": "missing-execution-model",
        }
        normalize_custom_provider_settings(settings)
        self.assertEqual(settings["llm_provider"], "groq")
        self.assertEqual(settings["llm_model"], "")
        self.assertEqual(settings["llm_planner_provider"], _PROVIDER)
        self.assertEqual(settings["llm_execution_provider"], "")
        self.assertEqual(settings["llm_execution_model"], "")

    def test_custom_key_is_encrypted_and_never_written_in_public_settings(self):
        settings = {
            "llm_provider": _PROVIDER,
            "llm_model": "model-x",
            "custom_llm_providers": {_PROVIDER: {**_METADATA, "api_key": "nested-sentinel"}},
            _API_KEY: "top-level-sentinel",
        }
        with _isolated_settings() as path, _opaque_crypto():
            self.assertTrue(ConfigManager.save_settings(settings))
            public = _read_json(path)
            public_text = path.read_text(encoding="utf-8")
            stored = SecretStore(path).read()

        self.assertNotIn(_API_KEY, public)
        self.assertNotIn("api_key", public["custom_llm_providers"][_PROVIDER])
        self.assertNotIn("top-level-sentinel", public_text)
        self.assertNotIn("nested-sentinel", public_text)
        self.assertEqual(stored, {_API_KEY: "top-level-sentinel"})

    def test_legacy_custom_plaintext_is_migrated_and_old_settings_stay_custom_free(self):
        with _isolated_settings() as path, _opaque_crypto():
            legacy_custom = {
                "llm_provider": _PROVIDER,
                "llm_model": "model-x",
                "custom_llm_providers": {_PROVIDER: _METADATA},
                _API_KEY: "legacy-sentinel",
            }
            path.write_text(json.dumps(legacy_custom), encoding="utf-8")
            settings = ConfigManager.load_settings()
            self.assertEqual(settings[_API_KEY], "legacy-sentinel")
            self.assertNotIn(_API_KEY, _read_json(path))
            self.assertEqual(SecretStore(path).read(), {_API_KEY: "legacy-sentinel"})
            self.assertTrue(list(path.parent.glob("ari_settings.pre-secrets.*.dpapi")))

        with _isolated_settings() as path, _opaque_crypto():
            path.write_text(json.dumps({"llm_provider": "groq", "llm_model": "legacy-model"}), encoding="utf-8")
            settings = ConfigManager.load_settings()
            self.assertEqual(settings["llm_provider"], "groq")
            self.assertEqual(settings["llm_model"], "legacy-model")
            self.assertNotIn("custom_llm_providers", _read_json(path))

    def test_deleting_provider_removes_secret_and_falls_back_all_roles(self):
        settings = {
            "llm_provider": _PROVIDER,
            "llm_model": "main-model",
            "llm_planner_provider": _PROVIDER,
            "llm_planner_model": "planner-model",
            "llm_execution_provider": _PROVIDER,
            "llm_execution_model": "execution-model",
            "custom_llm_providers": {_PROVIDER: _METADATA},
            _API_KEY: "delete-me-sentinel",
        }
        with _isolated_settings() as path, _opaque_crypto():
            self.assertTrue(ConfigManager.save_settings(settings))
            settings["custom_llm_providers"] = {}
            self.assertTrue(ConfigManager.save_settings(settings))

            public = _read_json(path)
            stored = SecretStore(path).read()

        self.assertEqual(public["llm_provider"], "groq")
        self.assertEqual(public["llm_model"], "")
        self.assertEqual(public["llm_planner_provider"], "")
        self.assertEqual(public["llm_planner_model"], "")
        self.assertEqual(public["llm_execution_provider"], "")
        self.assertEqual(public["llm_execution_model"], "")
        self.assertEqual(public["custom_llm_providers"], {})
        self.assertEqual(stored, {})


if __name__ == "__main__":
    unittest.main()
