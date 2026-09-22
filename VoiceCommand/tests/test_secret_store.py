import contextlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from core import secret_store
from core.config_manager import ConfigManager
from core.secret_store import SecretStore, SecretStoreError
from core.settings_schema import SENSITIVE_SETTINGS_KEYS


@contextlib.contextmanager
def _isolated_settings():
    with tempfile.TemporaryDirectory() as temp_dir:
        path = Path(temp_dir) / "ari_settings.json"
        with contextlib.ExitStack() as stack:
            stack.enter_context(
                patch("core.config_manager._settings_path", return_value=str(path))
            )
            stack.enter_context(patch.object(ConfigManager, "_cached_settings", None))
            stack.enter_context(patch.object(ConfigManager, "_dotenv_settings", {}))
            stack.enter_context(patch.dict(os.environ, {}, clear=True))
            yield path


@contextlib.contextmanager
def _opaque_crypto():
    tokens = {}

    def protect(data):
        token = f"opaque-token-{len(tokens)}".encode("ascii")
        tokens[token] = bytes(data)
        return token

    def unprotect(data):
        return tokens[bytes(data)]

    with patch.object(secret_store, "_protect", side_effect=protect):
        with patch.object(secret_store, "_unprotect", side_effect=unprotect):
            yield tokens


def _write_json(path, payload):
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


class SecretStoreTests(unittest.TestCase):
    def test_secret_precedence_is_environment_then_dotenv_then_encrypted_then_legacy(self):
        legacy = {
            "openai_api_key": "legacy-openai",
            "groq_api_key": "legacy-groq",
            "anthropic_api_key": "legacy-anthropic",
            "gemini_api_key": "legacy-gemini",
            "mistral_api_key": "legacy-mistral",
            "llm_provider": "groq",
        }
        encrypted = {
            "openai_api_key": "encrypted-openai",
            "groq_api_key": "encrypted-groq",
            "anthropic_api_key": "encrypted-anthropic",
            "gemini_api_key": "encrypted-gemini",
        }

        with _isolated_settings() as path:
            with _opaque_crypto():
                _write_json(path, legacy)
                SecretStore(path).write(encrypted)
                path.with_name(".env").write_text(
                    "ARI_OPENAI_API_KEY=dotenv-openai\n"
                    "ARI_GROQ_API_KEY=dotenv-groq\n",
                    encoding="utf-8",
                )
                os.environ["ARI_OPENAI_API_KEY"] = "environment-openai"

                settings = ConfigManager.load_settings()

        self.assertEqual(settings["openai_api_key"], "environment-openai")
        self.assertEqual(settings["groq_api_key"], "dotenv-groq")
        self.assertEqual(settings["anthropic_api_key"], "encrypted-anthropic")
        self.assertEqual(settings["gemini_api_key"], "encrypted-gemini")
        self.assertEqual(settings["mistral_api_key"], "legacy-mistral")

    def test_legacy_migration_backs_up_before_public_secret_removal(self):
        legacy = {"openai_api_key": "legacy-secret", "llm_provider": "groq"}

        with _isolated_settings() as path:
            with _opaque_crypto():
                _write_json(path, legacy)
                original = path.read_bytes()
                real_write_public = ConfigManager._write_public_settings

                def write_public(path_arg, settings):
                    backups = list(Path(path_arg).parent.glob("ari_settings.pre-secrets.*.dpapi"))
                    self.assertTrue(backups)
                    return real_write_public(path_arg, settings)

                with patch.object(
                    ConfigManager,
                    "_write_public_settings",
                    side_effect=write_public,
                ):
                    settings = ConfigManager.load_settings()

                backup = next(path.parent.glob("ari_settings.pre-secrets.*.dpapi"))
                self.assertEqual(secret_store._unprotect(backup.read_bytes()), original)
                self.assertEqual(settings["openai_api_key"], "legacy-secret")
                self.assertNotIn("openai_api_key", _read_json(path))
                self.assertEqual(SecretStore(path).read(), {"openai_api_key": "legacy-secret"})

    def test_all_sensitive_keys_are_encrypted_and_absent_from_public_json(self):
        values = {key: f"value-{key}" for key in SENSITIVE_SETTINGS_KEYS}

        with _isolated_settings() as path:
            with _opaque_crypto():
                self.assertEqual(len(SENSITIVE_SETTINGS_KEYS), 13)
                self.assertTrue(
                    ConfigManager.save_settings({"llm_provider": "openai", **values})
                )

                public = _read_json(path)
                stored = SecretStore(path).read()

        self.assertTrue(set(SENSITIVE_SETTINGS_KEYS).isdisjoint(public))
        self.assertEqual(stored, values)

    def test_setter_update_load_and_empty_value_clear_secret(self):
        with _isolated_settings() as path:
            with _opaque_crypto():
                self.assertTrue(ConfigManager.set_value("openai_api_key", "first"))
                self.assertEqual(ConfigManager.load_settings()["openai_api_key"], "first")

                self.assertTrue(
                    ConfigManager.update_settings(
                        lambda settings: settings.update(
                            {"openai_api_key": "second", "llm_provider": "openai"}
                        )
                    )
                )
                self.assertEqual(ConfigManager.load_settings()["openai_api_key"], "second")
                self.assertEqual(ConfigManager.get("llm_provider"), "openai")

                self.assertTrue(ConfigManager.set_value("openai_api_key", ""))
                self.assertEqual(ConfigManager.load_settings()["openai_api_key"], "")
                self.assertNotIn("openai_api_key", SecretStore(path).read())

    def test_environment_secret_is_not_copied_on_unrelated_public_save(self):
        with _isolated_settings() as path:
            os.environ["ARI_OPENAI_API_KEY"] = "environment-only"
            with _opaque_crypto():
                self.assertTrue(ConfigManager.save_settings({"llm_provider": "openai"}))
                settings = ConfigManager.load_settings()

                self.assertFalse(SecretStore(path).path.exists())
                self.assertEqual(settings["openai_api_key"], "environment-only")
                self.assertNotIn("openai_api_key", _read_json(path))

    def test_corrupt_store_degrades_to_empty_and_preserves_bytes_on_failed_save(self):
        with _isolated_settings() as path:
            _write_json(path, {"llm_provider": "groq"})
            store_path = SecretStore(path).path
            corrupt = b"corrupt-encrypted-bytes"
            store_path.write_bytes(corrupt)
            public_before = path.read_bytes()

            with patch.object(secret_store, "_unprotect", side_effect=ValueError("bad token")):
                settings = ConfigManager.load_settings()
                self.assertEqual(settings["openai_api_key"], "")
                with self.assertLogs(level="ERROR") as captured:
                    self.assertFalse(
                        ConfigManager.save_settings({"openai_api_key": "new-secret"})
                    )

            self.assertEqual(path.read_bytes(), public_before)
            self.assertEqual(store_path.read_bytes(), corrupt)
            self.assertNotIn("new-secret", "\n".join(captured.output))

    def test_encryption_failure_keeps_existing_files_and_does_not_log_secret(self):
        with _isolated_settings() as path:
            with _opaque_crypto():
                _write_json(path, {"llm_provider": "groq"})
                SecretStore(path).write({"openai_api_key": "old-secret"})
                public_before = path.read_bytes()
                encrypted_before = SecretStore(path).path.read_bytes()

                with patch.object(
                    secret_store,
                    "_protect",
                    side_effect=SecretStoreError("encryption failed"),
                ):
                    with self.assertLogs(level="ERROR") as captured:
                        self.assertFalse(
                            ConfigManager.save_settings(
                                {"llm_provider": "openai", "openai_api_key": "new-secret"}
                            )
                        )

                self.assertEqual(path.read_bytes(), public_before)
                self.assertEqual(SecretStore(path).path.read_bytes(), encrypted_before)
                self.assertNotIn("new-secret", "\n".join(captured.output))

    def test_partial_public_write_failure_does_not_overwrite_credentials(self):
        with _isolated_settings() as path:
            with _opaque_crypto():
                _write_json(path, {"llm_provider": "groq"})
                SecretStore(path).write({"openai_api_key": "old-secret"})
                public_before = path.read_bytes()
                encrypted_before = SecretStore(path).path.read_bytes()

                with patch.object(
                    ConfigManager,
                    "_write_public_settings",
                    side_effect=OSError("disk full"),
                ):
                    with self.assertLogs(level="ERROR") as captured:
                        self.assertFalse(
                            ConfigManager.save_settings(
                                {"llm_provider": "openai", "openai_api_key": "new-secret"}
                            )
                        )

                self.assertEqual(path.read_bytes(), public_before)
                self.assertEqual(SecretStore(path).path.read_bytes(), encrypted_before)
                self.assertNotIn("new-secret", "\n".join(captured.output))

    def test_failed_migration_keeps_legacy_file_and_retries_after_cache_reset(self):
        original_settings = {"llm_provider": "groq", "openai_api_key": "legacy-secret"}

        with _isolated_settings() as path:
            with _opaque_crypto():
                _write_json(path, original_settings)
                original = path.read_bytes()
                with patch.object(
                    SecretStore,
                    "backup",
                    side_effect=SecretStoreError("backup failed"),
                ):
                    with self.assertLogs(level="WARNING") as captured:
                        first = ConfigManager.load_settings()

                self.assertEqual(first["openai_api_key"], "legacy-secret")
                self.assertEqual(path.read_bytes(), original)
                self.assertNotIn("legacy-secret", "\n".join(captured.output))

                ConfigManager._cached_settings = None
                second = ConfigManager.load_settings()
                self.assertNotIn("openai_api_key", _read_json(path))
                self.assertEqual(SecretStore(path).read(), {"openai_api_key": "legacy-secret"})
                self.assertEqual(second["openai_api_key"], "legacy-secret")

    def test_migration_write_failure_keeps_original_settings_and_secret_out_of_logs(self):
        original_settings = {"llm_provider": "groq", "openai_api_key": "legacy-secret"}

        with _isolated_settings() as path:
            with _opaque_crypto():
                _write_json(path, original_settings)
                original = path.read_bytes()
                with patch.object(
                    SecretStore,
                    "write",
                    side_effect=SecretStoreError("write failed"),
                ):
                    with self.assertLogs(level="WARNING") as captured:
                        settings = ConfigManager.load_settings()

                self.assertEqual(settings["openai_api_key"], "legacy-secret")
                self.assertEqual(path.read_bytes(), original)
                self.assertNotIn("legacy-secret", "\n".join(captured.output))

    @unittest.skipIf(sys.platform == "win32", "non-Windows fallback semantics")
    def test_nonwindows_allows_env_legacy_readonly_and_public_only_save(self):
        original_settings = {"llm_provider": "groq", "openai_api_key": "legacy-secret"}

        with _isolated_settings() as path:
            _write_json(path, original_settings)
            original = path.read_bytes()
            os.environ["ARI_OPENAI_API_KEY"] = "environment-secret"

            with self.assertLogs(level="WARNING") as captured:
                settings = ConfigManager.load_settings()

            self.assertEqual(settings["openai_api_key"], "environment-secret")
            self.assertEqual(_read_json(path)["openai_api_key"], "legacy-secret")
            self.assertNotIn("environment-secret", "\n".join(captured.output))

            with self.assertLogs(level="ERROR") as save_logs:
                self.assertFalse(ConfigManager.save_settings({"openai_api_key": "new-secret"}))
            self.assertEqual(path.read_bytes(), original)
            self.assertNotIn("new-secret", "\n".join(save_logs.output))

            self.assertTrue(ConfigManager.save_settings({"llm_provider": "openai"}))
            public = _read_json(path)
            self.assertEqual(public["llm_provider"], "openai")
            self.assertEqual(public["openai_api_key"], "legacy-secret")

    def test_secret_store_rejects_invalid_versions_types_and_fields(self):
        invalid_payloads = (
            {"version": 2, "secrets": {}},
            {"version": 1, "secrets": []},
            {"version": 1, "secrets": {"unknown_field": "value"}},
            {"version": 1, "secrets": {"openai_api_key": 123}},
        )

        with _isolated_settings() as path:
            with _opaque_crypto() as tokens:
                store = SecretStore(path)
                for index, payload in enumerate(invalid_payloads):
                    with self.subTest(index=index):
                        token = f"invalid-token-{index}".encode("ascii")
                        tokens[token] = json.dumps(payload).encode("utf-8")
                        store.path.write_bytes(token)
                        with self.assertRaises(SecretStoreError):
                            store.read()

                with self.assertRaises(SecretStoreError):
                    store.write({"unknown_field": "value"})
                with self.assertRaises(SecretStoreError):
                    store.write({"openai_api_key": 123})

    @unittest.skipUnless(sys.platform == "win32", "Windows DPAPI is unavailable")
    def test_real_windows_dpapi_roundtrip_for_test_secret(self):
        try:
            import win32crypt  # noqa: F401
        except ImportError:
            self.skipTest("pywin32 win32crypt is unavailable")

        secret = b"test-only-dpapi-secret"
        protected = secret_store._protect(secret)
        self.assertEqual(secret_store._unprotect(protected), secret)


if __name__ == "__main__":
    unittest.main()
