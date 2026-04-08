import unittest


from tts.tts_factory import build_tts_signature


class TTSFactoryTests(unittest.TestCase):
    def test_tts_signature_changes_only_with_tts_related_fields(self):
        base = {
            "tts_mode": "fish",
            "fish_api_key": "a",
            "fish_reference_id": "b",
            "personality": "x",
        }
        same = dict(base, personality="y")
        changed = dict(base, fish_reference_id="c")

        self.assertEqual(build_tts_signature(base), build_tts_signature(same))
        self.assertNotEqual(build_tts_signature(base), build_tts_signature(changed))


if __name__ == "__main__":
    unittest.main()
