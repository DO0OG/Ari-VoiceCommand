import ast
import gettext
import os
import tempfile
import unittest
from pathlib import Path

from scripts.compile_po import compile_po
from scripts.extract_strings import _PY_FILES


class CompilePoTests(unittest.TestCase):
    def test_all_literal_translations_are_registered(self):
        project_root = Path(__file__).resolve().parents[1]
        msgids = set()
        for source_path in _PY_FILES:
            tree = ast.parse(Path(source_path).read_text(encoding="utf-8-sig"))
            for node in ast.walk(tree):
                if not (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id == "_"
                    and node.args
                ):
                    continue
                try:
                    msgid = ast.literal_eval(node.args[0])
                except (ValueError, TypeError):
                    continue
                if isinstance(msgid, str):
                    msgids.add(msgid)

        catalogs = {}
        with tempfile.TemporaryDirectory() as tmp:
            for language in ("ko", "en", "ja"):
                po_path = project_root / "i18n" / "locales" / language / "LC_MESSAGES" / "ari.po"
                mo_path = Path(tmp) / f"{language}.mo"
                compile_po(str(po_path), str(mo_path))
                with mo_path.open("rb") as handle:
                    catalogs[language] = gettext.GNUTranslations(handle)._catalog

        for language, catalog in catalogs.items():
            missing = sorted(msgids - catalog.keys())
            self.assertEqual(missing, [], f"{language} missing msgids: {missing}")
        for language in ("en", "ja"):
            empty = sorted(msgid for msgid in msgids if not catalogs[language].get(msgid))
            self.assertEqual(empty, [], f"{language} empty msgstrs: {empty}")

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
