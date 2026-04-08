import unittest


from ui.theme_runtime import apply_live_theme


class _DummyTextInterface:
    def __init__(self):
        self.refreshed = 0

    def refresh_theme(self):
        self.refreshed += 1


class _DummyTray:
    def __init__(self, text_interface):
        self.text_interface = text_interface
        self.menu_refreshed = 0

    def _apply_menu_theme(self):
        self.menu_refreshed += 1


class _DummyCharacter:
    def __init__(self, text_interface):
        self.text_interface = text_interface
        self.refreshed = 0

    def refresh_theme(self):
        self.refreshed += 1


class ThemeRuntimeTests(unittest.TestCase):
    def test_apply_live_theme_refreshes_existing_widgets(self):
        text_interface = _DummyTextInterface()
        tray = _DummyTray(text_interface)
        character = _DummyCharacter(text_interface)

        apply_live_theme(tray_icon=tray, character_widget=character)

        self.assertEqual(tray.menu_refreshed, 1)
        self.assertEqual(text_interface.refreshed, 1)
        self.assertEqual(character.refreshed, 1)


if __name__ == "__main__":
    unittest.main()
