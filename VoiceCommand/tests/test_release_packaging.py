import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from core import release_packaging


class ReleasePackagingTests(unittest.TestCase):
    def test_raw_package_includes_binary_tree_sibling_libs_and_declared_alias_imports(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            site_packages = Path(temp_dir)
            package_dir = site_packages / "pandas"
            package_dir.mkdir()
            (package_dir / "__init__.py").write_text(
                "import pandas._libs\n"
                "from dateutil import parser\n"
                "import et_xmlfile\n"
                "from PIL import Image\n"
                "import optional_plugin\n",
                encoding="utf-8",
            )
            extension = package_dir / "_libs" / "sample.cp311-win_amd64.pyd"
            extension.parent.mkdir()
            extension.write_bytes(b"native extension")
            libs_dir = site_packages / "pandas.libs"
            libs_dir.mkdir()
            (libs_dir / "native.dll").write_bytes(b"native dependency")

            module_locations = {
                "pandas": package_dir,
                "dateutil": site_packages / "dateutil",
                "et_xmlfile": site_packages / "et_xmlfile",
                "PIL": site_packages / "PIL",
                "optional_plugin": site_packages / "optional_plugin",
            }
            packages_by_import = {
                "pandas": ["pandas"],
                "dateutil": ["python-dateutil"],
                "et_xmlfile": ["et-xmlfile"],
                "PIL": ["Pillow"],
                "optional_plugin": ["optional-plugin"],
            }

            def find_spec(name):
                location = module_locations.get(name)
                if location is None:
                    return None
                return SimpleNamespace(submodule_search_locations=[str(location)])

            with (
                patch.object(release_packaging.importlib.util, "find_spec", side_effect=find_spec),
                patch.object(
                    release_packaging.importlib.metadata,
                    "packages_distributions",
                    return_value=packages_by_import,
                ),
                patch.object(
                    release_packaging.importlib.metadata,
                    "requires",
                    return_value=[
                        "python-dateutil>=2.8",
                        "et-xmlfile>=1.0",
                        "Pillow>=9",
                        'optional-plugin; extra == "excel"',
                    ],
                ),
            ):
                args = release_packaging.raw_packages("pandas")

        self.assertTrue(extension.exists() is False)  # Temporary tree was cleaned after arguments were built.
        self.assertIn(f"--include-raw-dir={package_dir}=pandas", args)
        self.assertIn(f"--include-raw-dir={libs_dir}=pandas.libs", args)
        self.assertIn("--nofollow-import-to=pandas", args)
        self.assertIn("--include-package=dateutil", args)
        self.assertIn("--include-package=et_xmlfile", args)
        self.assertIn("--include-package=PIL", args)
        self.assertNotIn("--include-package=optional_plugin", args)

    def test_raw_dependencies_copies_third_party_deps_but_compiles_app_dependencies(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            site_packages = Path(temp_dir)
            for name in ("pandas", "dateutil", "PIL"):
                (site_packages / name).mkdir()
            (site_packages / "pandas" / "__init__.py").write_text(
                "from dateutil import parser\nfrom PIL import Image\n", encoding="utf-8"
            )
            requires = {"pandas": ["python-dateutil>=2.8", "Pillow>=9"], "dateutil": []}

            def find_spec(name):
                path = site_packages / name
                return SimpleNamespace(submodule_search_locations=[str(path)]) if path.exists() else None

            with (
                patch.object(release_packaging.importlib.util, "find_spec", side_effect=find_spec),
                patch.object(
                    release_packaging.importlib.metadata,
                    "packages_distributions",
                    return_value={"pandas": ["pandas"], "dateutil": ["python-dateutil"], "PIL": ["Pillow"]},
                ),
                patch.object(
                    release_packaging.importlib.metadata,
                    "requires",
                    side_effect=lambda name: requires.get(name, []),
                ),
            ):
                args = release_packaging.raw_packages("pandas", raw_dependencies=True)

        self.assertIn(f"--include-raw-dir={site_packages / 'dateutil'}=dateutil", args)
        self.assertIn("--nofollow-import-to=dateutil", args)
        self.assertNotIn("--include-package=dateutil", args)
        self.assertIn("--include-package=PIL", args)


if __name__ == "__main__":
    unittest.main()
