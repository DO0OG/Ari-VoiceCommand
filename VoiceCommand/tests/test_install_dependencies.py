import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import install_dependencies


class InstallDependenciesTests(unittest.TestCase):
    def test_open_jtalk_install_skips_its_transitive_dictionary(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            requirements = Path(temp_dir) / "requirements.txt"
            captured = {}
            requirements.write_text(
                "numpy>=1.26\npyopenjtalk-plus==0.4.1.post9\nsudachipy>=0.6.8\n",
                encoding="utf-8",
            )

            def record_pip(_python_exe, *arguments):
                if arguments[:2] == ("install", "-r"):
                    captured["filtered_requirements"] = Path(arguments[2]).read_text(
                        encoding="utf-8"
                    )

            with (
                patch.object(install_dependencies, "REQUIREMENTS", requirements),
                patch.object(
                    install_dependencies, "_run_pip", side_effect=record_pip
                ) as run_pip,
            ):
                install_dependencies._install_main_dependencies(Path("python.exe"))

        self.assertEqual(run_pip.call_count, 3)
        filtered_text = captured["filtered_requirements"]
        self.assertIn("numpy>=1.26", filtered_text)
        self.assertIn("sudachipy>=0.6.8", filtered_text)
        self.assertNotIn("pyopenjtalk-plus", filtered_text)
        self.assertEqual(run_pip.call_args_list[2].args[1:], (
            "install", "--no-deps", "pyopenjtalk-plus==0.4.1.post9"
        ))


if __name__ == "__main__":
    unittest.main()
