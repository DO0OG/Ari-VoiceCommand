import gettext
import os
import tempfile
import unittest

from scripts.compile_po import compile_po


class CompilePoTests(unittest.TestCase):
    def test_compile_po_accepts_utf8_bom_header(self):
        with tempfile.TemporaryDirectory() as tmp:
            po_path = os.path.join(tmp, "ari.po")
            mo_path = os.path.join(tmp, "ari.mo")

            payload = (
                '\ufeffmsgid ""\n'
                'msgstr ""\n'
                '"Project-Id-Version: Ari 1.0\\n"\n'
                '"Content-Type: text/plain; charset=UTF-8\\n"\n'
                '"Language: ko\\n"\n'
                "\n"
                'msgid "테스트"\n'
                'msgstr "테스트 😀"\n'
            )

            with open(po_path, "w", encoding="utf-8") as handle:
                handle.write(payload)

            compile_po(po_path, mo_path)

            with open(mo_path, "rb") as handle:
                translations = gettext.GNUTranslations(handle)

            self.assertEqual(translations.gettext("테스트"), "테스트 😀")


if __name__ == "__main__":
    unittest.main()
