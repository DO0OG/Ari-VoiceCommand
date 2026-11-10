import gettext
import os
import tempfile
import unittest
from unittest.mock import patch


from core.config_manager import ConfigManager
from i18n import translator
from scripts.compile_po import compile_po
from ui import theme


class ThemeConfigTests(unittest.TestCase):
    def test_default_settings_include_split_models_and_theme_options(self):
        defaults = ConfigManager.DEFAULT_SETTINGS
        self.assertIn("llm_planner_model", defaults)
        self.assertIn("llm_execution_model", defaults)
        self.assertIn("ui_theme_preset", defaults)
        self.assertIn("ui_theme_scale", defaults)

    def test_theme_presets_and_metadata_are_available(self):
        presets = dict(theme.available_theme_presets())
        self.assertIn("default", presets)
        self.assertIn("sunset", presets)
        self.assertIn("forest", presets)
        meta = theme.theme_metadata()
        self.assertIn("preset_key", meta)
        self.assertIn("theme_dir", meta)
        self.assertGreaterEqual(theme.FONT_SIZE_NORMAL, 7)

    def test_preset_names_follow_language_but_custom_names_are_kept(self):
        project_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with tempfile.TemporaryDirectory() as tmp:
            mo_path = os.path.join(tmp, "en.mo")
            compile_po(os.path.join(project_dir, "i18n", "locales", "en", "LC_MESSAGES", "ari.po"), mo_path)
            with open(mo_path, "rb") as handle:
                english = gettext.GNUTranslations(handle)
            with open(os.path.join(tmp, "custom.json"), "w", encoding="utf-8") as handle:
                handle.write('{"id":"custom","name":"커스텀"}')
            with patch.object(translator, "_translation", english):
                builtin = dict(theme.available_theme_presets())
                with patch.object(theme, "theme_dir", lambda: tmp):
                    custom = dict(theme.available_theme_presets())

        self.assertEqual(builtin["default"], "Default Blue")
        self.assertEqual(custom["custom"], "커스텀")

    def test_theme_loader_reads_external_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            custom_path = os.path.join(tmp, "custom.json")
            with open(custom_path, "w", encoding="utf-8") as handle:
                handle.write('{"id":"custom","name":"커스텀","font_family":"맑은 고딕","colors":{"primary":"#123456"}}')

            original_theme_dir = theme.theme_dir
            try:
                theme.theme_dir = lambda: tmp
                presets = dict(theme.available_theme_presets())
                palette = theme.load_theme_palette("custom")
            finally:
                theme.theme_dir = original_theme_dir

            self.assertIn("custom", presets)
            self.assertEqual(palette.colors["primary"], "#123456")

    def test_save_custom_theme_writes_json_palette(self):
        with tempfile.TemporaryDirectory() as tmp:
            original_theme_dir = theme.theme_dir
            try:
                theme.theme_dir = lambda: tmp
                saved_path = theme.save_custom_theme("custom_night", "커스텀 나이트", {"primary": "#111111"})
                palette = theme.load_theme_palette("custom_night")
            finally:
                theme.theme_dir = original_theme_dir

            self.assertTrue(os.path.exists(saved_path))
            self.assertEqual(palette.colors["primary"], "#111111")


if __name__ == "__main__":
    unittest.main()
