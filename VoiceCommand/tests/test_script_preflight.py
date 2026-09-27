import os
import tempfile
import unittest
from unittest.mock import patch

from core.script_preflight import find_unavailable_imports


class ScriptPreflightTests(unittest.TestCase):
    def test_finds_required_imports_but_ignores_optional_or_unexecuted_code(self):
        source = '''
import required_missing
try:
    import optional_missing
except ImportError:
    import fallback_missing

def unused():
    import function_only_missing
if False:
    import static_branch_missing
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    import type_only_missing
else:
    import runtime_missing
if importlib.util.find_spec("guarded_missing") is not None:
    import guarded_missing
'''
        with patch("core.script_preflight.importlib.util.find_spec", return_value=None):
            unavailable = find_unavailable_imports(source)

        self.assertEqual(
            unavailable,
            ["fallback_missing", "required_missing", "runtime_missing"],
        )

    def test_ignores_modules_available_as_local_files_or_namespace_directories(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            open(os.path.join(temp_dir, "local_module.py"), "w", encoding="utf-8").close()
            os.mkdir(os.path.join(temp_dir, "namespace_package"))
            source = "import local_module\nimport namespace_package"

            with patch("core.script_preflight.importlib.util.find_spec", return_value=None):
                self.assertEqual(find_unavailable_imports(source, (temp_dir,)), [])


if __name__ == "__main__":
    unittest.main()