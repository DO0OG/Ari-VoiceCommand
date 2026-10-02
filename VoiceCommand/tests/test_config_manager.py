import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.config_manager import ConfigManager


class ConfigManagerTests(unittest.TestCase):
    def tearDown(self):
        ConfigManager._settings_read_failed = False

    def test_normalize_settings_rejects_bool_for_int_field(self):
        with patch.object(
            ConfigManager,
            "DEFAULT_SETTINGS",
            {
                "stt_energy_threshold": 300,
                "weekly_report_enabled": False,
                "agent_response_cache_ttl": 600,
            },
        ):
            normalized = ConfigManager._normalize_settings(
                {
                    "stt_energy_threshold": True,
                    "weekly_report_enabled": False,
                    "agent_response_cache_ttl": "fast",
                }
            )

        self.assertEqual(normalized["stt_energy_threshold"], 300)
        self.assertEqual(normalized["agent_response_cache_ttl"], 600)

    def test_normalize_settings_rejects_non_bool_for_bool_field(self):
        with patch.object(
            ConfigManager,
            "DEFAULT_SETTINGS",
            {"stt_energy_threshold": 300, "weekly_report_enabled": False},
        ):
            normalized = ConfigManager._normalize_settings(
                {"stt_energy_threshold": 300, "weekly_report_enabled": 1}
            )

        self.assertFalse(normalized["weekly_report_enabled"])


    def test_save_settings_keeps_previous_file_when_write_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "settings.json")
            original = {"stt_energy_threshold": 300}
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(original, handle)

            with patch("core.config_manager._settings_path", return_value=path):
                with patch("core.config_manager.json.dump", side_effect=OSError("disk full")):
                    saved = ConfigManager.save_settings({"stt_energy_threshold": 500})

            self.assertFalse(saved)
            with open(path, encoding="utf-8") as handle:
                self.assertEqual(json.load(handle), original)
            self.assertEqual(os.listdir(tmp), ["settings.json"])

    def test_save_settings_repairs_corrupt_json_and_keeps_secret_private(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "ari_settings.json")
            with open(path, "wb") as handle:
                handle.write(b"{broken")
            previous = ConfigManager._cached_settings
            try:
                with patch("core.config_manager._settings_path", return_value=path), \
                        patch("core.config_manager.SecretStore.read", return_value={}), \
                        patch("core.config_manager.SecretStore.write"):
                    ConfigManager._cached_settings = None
                    self.assertTrue(ConfigManager.save_settings({
                        "stt_energy_threshold": 500,
                        "openai_api_key": "private-key",
                    }))
                with open(path, encoding="utf-8") as handle:
                    saved = json.load(handle)
                backups = [name for name in os.listdir(tmp) if ".corrupt-" in name]
                self.assertEqual(saved["stt_energy_threshold"], 500)
                self.assertNotIn("openai_api_key", saved)
                self.assertEqual(len(backups), 1)
                with open(os.path.join(tmp, backups[0]), "rb") as handle:
                    self.assertEqual(handle.read(), b"{broken")
            finally:
                ConfigManager._cached_settings = previous

    def test_load_settings_backs_up_same_corrupt_file_only_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "ari_settings.json")
            with open(path, "wb") as handle:
                handle.write(b"{broken")
            previous = ConfigManager._cached_settings
            try:
                with patch("core.config_manager._settings_path", return_value=path):
                    for _ in range(2):
                        ConfigManager._cached_settings = None
                        ConfigManager.load_settings()
                backups = [name for name in os.listdir(tmp) if ".corrupt-" in name]
                self.assertEqual(len(backups), 1)
            finally:
                ConfigManager._cached_settings = previous

    def test_corrupt_settings_save_preserves_unlisted_custom_provider_secret(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "ari_settings.json")
            with open(path, "wb") as handle:
                handle.write(b"{broken")
            key = "custom_0123456789abcdef0123456789abcdef_api_key"
            with patch("core.config_manager._settings_path", return_value=path), \
                    patch("core.config_manager.SecretStore.read", return_value={key: "secret"}), \
                    patch("core.config_manager.SecretStore.write") as write:
                self.assertTrue(ConfigManager.save_settings({"custom_llm_providers": {}}))
                # 키가 그대로 남으므로 비밀 저장소를 다시 쓰지 않는다.
                write.assert_not_called()

    def test_corrupt_settings_backup_skips_unreadable_candidate_and_creates_one(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ari_settings.json"
            candidate = Path(tmp) / "ari_settings.corrupt-old.json"
            path.write_bytes(b"{broken")
            candidate.write_bytes(b"unreadable candidate")
            read_bytes = Path.read_bytes

            def read(candidate_path):
                if candidate_path == candidate:
                    raise PermissionError("unreadable")
                return read_bytes(candidate_path)

            with patch.object(Path, "read_bytes", read):
                self.assertTrue(ConfigManager._backup_corrupt_settings(str(path)))
            backups = [item for item in Path(tmp).glob("ari_settings.corrupt-*.json") if item != candidate]
            self.assertEqual(len(backups), 1)
            self.assertEqual(backups[0].read_bytes(), b"{broken")

    def test_corrupt_backup_failure_keeps_original_and_fails_save(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "ari_settings.json")
            with open(path, "wb") as handle:
                handle.write(b"{broken")
            with patch("core.config_manager._settings_path", return_value=path), \
                    patch("core.config_manager.backup_corrupt_file", side_effect=OSError("disk full")):
                self.assertFalse(ConfigManager.save_settings({"stt_energy_threshold": 500}))
            with open(path, "rb") as handle:
                self.assertEqual(handle.read(), b"{broken")

    def test_access_failure_then_save_keeps_user_settings_and_applies_only_the_change(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ari_settings.json"
            path.write_text('{"llm_provider":"openai"}', encoding="utf-8")
            read_bytes = Path.read_bytes
            blocked = True

            def read(candidate):
                nonlocal blocked
                if candidate == path and blocked:
                    blocked = False
                    raise PermissionError("temporarily unreadable")
                return read_bytes(candidate)

            previous = ConfigManager._cached_settings
            try:
                with patch("core.config_manager._settings_path", return_value=str(path)), \
                        patch.object(Path, "read_bytes", read), \
                        patch("core.config_manager.SecretStore.read", return_value={}):
                    ConfigManager._cached_settings = None
                    defaults = ConfigManager.load_settings()
                    self.assertEqual(defaults["llm_provider"], "groq")
                    self.assertTrue(ConfigManager.save_settings({**defaults, "stt_energy_threshold": 500}))
            finally:
                ConfigManager._cached_settings = previous
            # 기본값이 아니라 다시 읽은 사용자 설정 위에 바뀐 값만 얹어 저장한다.
            saved = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(saved["llm_provider"], "openai")
            self.assertEqual(saved["stt_energy_threshold"], 500)
            self.assertEqual(list(Path(tmp).glob("*.corrupt-*.json")), [])

    def test_access_failure_then_adding_provider_keeps_existing_providers_and_secrets(self):
        existing = "custom_0123456789abcdef0123456789abcdef"
        added = "custom_fedcba9876543210fedcba9876543210"
        details = {"label": "x", "base_url": "https://example.com/v1", "default_model": "m"}
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "ari_settings.json")
            with open(path, "w", encoding="utf-8") as handle:
                json.dump({"custom_llm_providers": {existing: details}}, handle)
            self.addCleanup(setattr, ConfigManager, "_cached_settings", ConfigManager._cached_settings)
            ConfigManager._settings_read_failed = True
            ConfigManager._cached_settings = dict(ConfigManager.DEFAULT_SETTINGS)
            with patch("core.config_manager._settings_path", return_value=path), \
                    patch("core.config_manager.SecretStore.read", return_value={existing + "_api_key": "secret"}), \
                    patch("core.config_manager.SecretStore.write") as write:
                self.assertTrue(ConfigManager.save_settings({"custom_llm_providers": {added: details}}))
                write.assert_not_called()
            with open(path, encoding="utf-8") as handle:
                saved = json.load(handle)
            # 기본값 화면에서 추가한 제공자가 파일에 있던 제공자를 지우지 않는다.
            self.assertEqual(set(saved["custom_llm_providers"]), {existing, added})

    def test_removing_custom_provider_from_valid_settings_removes_its_secret(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "ari_settings.json")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write('{"custom_llm_providers": {"custom_0123456789abcdef0123456789abcdef": {"label": "x", "base_url": "https://example.com/v1", "default_model": "m"}}}')
            key = "custom_0123456789abcdef0123456789abcdef_api_key"
            with patch("core.config_manager._settings_path", return_value=path), \
                    patch("core.config_manager.SecretStore.read", return_value={key: "secret"}), \
                    patch("core.config_manager.SecretStore.write") as write:
                self.assertTrue(ConfigManager.save_settings({"custom_llm_providers": {}}))
                self.assertNotIn(key, write.call_args.args[0])

    def test_custom_provider_secret_survives_saves_when_its_provider_was_lost_not_removed(self):
        key = "custom_0123456789abcdef0123456789abcdef_api_key"
        # 손상 복구 뒤의 저장(파일에 제공자가 없음)과 읽기 실패 뒤의 저장(기본값으로 실행 중)
        self.addCleanup(setattr, ConfigManager, "_cached_settings", ConfigManager._cached_settings)
        for content, read_failed in (('{"custom_llm_providers": {}}', False),
                                     ('{"custom_llm_providers": {"custom_0123456789abcdef0123456789abcdef": {"label": "x", "base_url": "https://example.com/v1", "default_model": "m"}}}', True)):
            with self.subTest(read_failed=read_failed), tempfile.TemporaryDirectory() as tmp:
                path = os.path.join(tmp, "ari_settings.json")
                with open(path, "w", encoding="utf-8") as handle:
                    handle.write(content)
                ConfigManager._settings_read_failed = read_failed
                ConfigManager._cached_settings = dict(ConfigManager.DEFAULT_SETTINGS)
                with patch("core.config_manager._settings_path", return_value=path), \
                        patch("core.config_manager.SecretStore.read", return_value={key: "secret"}), \
                        patch("core.config_manager.SecretStore.write") as write:
                    self.assertTrue(ConfigManager.save_settings({"custom_llm_providers": {}}))
                    write.assert_not_called()
                with open(path, encoding="utf-8") as handle:
                    saved = json.load(handle)
                # 읽기 실패 뒤에는 파일의 제공자 목록도 그대로 남는다.
                self.assertEqual(bool(saved["custom_llm_providers"]), read_failed)

    def test_local_decision_contradictions_are_normalized(self):
        from core.settings_schema import normalize_local_decision_settings

        cases = (
            ({"local_decision_mode": "adaptive", "local_decision_direct_execution": True}, "fast", True),
            ({"local_decision_mode": "adaptive", "local_decision_direct_execution": False}, "off", False),
            ({"local_decision_mode": "turbo", "local_decision_direct_execution": True}, "off", False),
            ({"local_decision_mode": "shadow", "local_decision_direct_execution": True}, "shadow", False),
            ({"local_decision_mode": "fast", "local_decision_direct_execution": False}, "fast", False),
        )
        for settings, mode, direct in cases:
            with self.subTest(settings=dict(settings)):
                normalize_local_decision_settings(settings)
                self.assertEqual(settings["local_decision_mode"], mode)
                self.assertIs(settings["local_decision_direct_execution"], direct)

    def test_v2_default_off_moves_to_fast_once_and_shadow_choice_stays(self):
        previous = ConfigManager._cached_settings
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "settings.json")
            with open(path, "w", encoding="utf-8") as handle:
                json.dump({
                    "local_decision_mode": "off",
                    "local_decision_direct_execution": False,
                    "local_decision_settings_version": 2,
                }, handle)
            try:
                with patch("core.config_manager._settings_path", return_value=path):
                    ConfigManager._cached_settings = None
                    self.assertEqual(ConfigManager.get("local_decision_mode"), "fast")
                    self.assertIs(ConfigManager.get("local_decision_direct_execution"), True)
                    with open(path, encoding="utf-8") as handle:
                        stored = json.load(handle)
                    self.assertEqual(stored["local_decision_mode"], "fast")
                    self.assertTrue(stored["local_decision_direct_execution"])
                    self.assertEqual(stored["local_decision_settings_version"], 3)

                    stored["local_decision_mode"] = "off"
                    stored["local_decision_direct_execution"] = False
                    with open(path, "w", encoding="utf-8") as handle:
                        json.dump(stored, handle)
                    ConfigManager._cached_settings = None
                    self.assertEqual(ConfigManager.get("local_decision_mode"), "off")

                    stored["local_decision_mode"] = "shadow"
                    stored["local_decision_settings_version"] = 2
                    with open(path, "w", encoding="utf-8") as handle:
                        json.dump(stored, handle)
                    ConfigManager._cached_settings = None
                    self.assertEqual(ConfigManager.get("local_decision_mode"), "shadow")
                    self.assertFalse(ConfigManager.get("local_decision_direct_execution"))
                    with open(path, encoding="utf-8") as handle:
                        stored = json.load(handle)
                    self.assertEqual(stored["local_decision_settings_version"], 3)
            finally:
                ConfigManager._cached_settings = previous

    def test_stt_migration_resets_only_unusable_threshold(self):
        from core.settings_schema import migrate_stt_settings

        cases = (
            ({"stt_energy_threshold": 0}, 300),
            ({"stt_energy_threshold": 0, "stt_settings_version": 1}, 300),
            ({"stt_energy_threshold": "x"}, 300),
            ({"stt_energy_threshold": "NaN"}, 300),
            ({"stt_energy_threshold": 10**400}, 300),
            ({"stt_energy_threshold": 7}, 7),
            ({"stt_energy_threshold": 15, "stt_settings_version": 1}, 15),
        )
        for settings, expected in cases:
            with self.subTest(settings=settings):
                self.assertTrue(migrate_stt_settings(settings))
                self.assertEqual(settings["stt_energy_threshold"], expected)
                self.assertEqual(settings["stt_settings_version"], 2)

        reenabled = {"stt_dynamic_energy": True, "stt_settings_version": 1}
        migrate_stt_settings(reenabled)
        self.assertTrue(reenabled["stt_dynamic_energy"])
        self.assertFalse(migrate_stt_settings({"stt_energy_threshold": 15, "stt_settings_version": 2}))
        # 이전 버전이 남긴 값은 설정 버전이 같아도 되돌린다.
        stale = {"stt_energy_threshold": 0, "stt_settings_version": 2}
        self.assertTrue(migrate_stt_settings(stale))
        self.assertEqual(stale["stt_energy_threshold"], 300)

    def test_legacy_auto_energy_is_disabled_once_without_changing_manual_threshold(self):
        previous = ConfigManager._cached_settings
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "settings.json")
            with open(path, "w", encoding="utf-8") as handle:
                json.dump({"stt_dynamic_energy": True, "stt_energy_threshold": 7}, handle)
            try:
                with patch("core.config_manager._settings_path", return_value=path):
                    ConfigManager._cached_settings = None
                    self.assertFalse(ConfigManager.get("stt_dynamic_energy"))
                    self.assertEqual(ConfigManager.get("stt_energy_threshold"), 7)
                    with open(path, encoding="utf-8") as handle:
                        stored = json.load(handle)
                    self.assertFalse(stored["stt_dynamic_energy"])
                    self.assertEqual(stored["stt_energy_threshold"], 7)
                    self.assertEqual(stored["stt_settings_version"], 2)

                    stored["stt_dynamic_energy"] = True
                    with open(path, "w", encoding="utf-8") as handle:
                        json.dump(stored, handle)
                    ConfigManager._cached_settings = None
                    self.assertTrue(ConfigManager.get("stt_dynamic_energy"))
            finally:
                ConfigManager._cached_settings = previous

    def test_shadow_stays_diagnostic_mode_across_settings_migrations(self):
        from core.settings_schema import migrate_local_decision_settings

        for version in (None, 1, 2):
            with self.subTest(version=version):
                settings = {
                    "local_decision_mode": "shadow",
                    "local_decision_direct_execution": False,
                }
                if version is not None:
                    settings["local_decision_settings_version"] = version

                migrate_local_decision_settings(settings)

                self.assertEqual(settings["local_decision_mode"], "shadow")
                self.assertFalse(settings["local_decision_direct_execution"])
                self.assertEqual(settings["local_decision_settings_version"], 3)

    def test_explicit_fast_choice_survives_migration(self):
        from core.settings_schema import migrate_local_decision_settings

        settings = {"local_decision_mode": "fast", "local_decision_direct_execution": True}
        migrate_local_decision_settings(settings)
        self.assertEqual(settings["local_decision_mode"], "fast")
        self.assertTrue(settings["local_decision_direct_execution"])


if __name__ == "__main__":
    unittest.main()
