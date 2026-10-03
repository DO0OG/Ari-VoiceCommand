import unittest


from agent.safety_checker import DangerLevel, SafetyChecker


class SafetyCheckerTests(unittest.TestCase):
    def setUp(self):
        self.checker = SafetyChecker()

    def test_sensitive_url_is_blocked(self):
        report = self.checker.check_url("https://example.com/delete-account")
        self.assertEqual(report.level, DangerLevel.DANGEROUS)
        self.assertEqual(report.category, "web")

    def test_trusted_app_is_safe_but_blocked_admin_tool_is_not(self):
        self.assertEqual(self.checker.check_app_launch("notepad").level, DangerLevel.SAFE)
        self.assertEqual(self.checker.check_app_launch("regedit").level, DangerLevel.DANGEROUS)

    def test_restart_and_logoff_shell_are_dangerous(self):
        self.assertEqual(self.checker.check_shell("shutdown /r /t 0").level, DangerLevel.DANGEROUS)
        self.assertEqual(self.checker.check_shell("logoff").level, DangerLevel.DANGEROUS)

    def test_powershell_destructive_commands_are_dangerous(self):
        for command in (
            "Remove-Item -Recurse -Force C:/Users/x/Documents",
            "rm -r -fo C:/x",
            "Stop-Computer",
            "Format-Volume -DriveLetter D",
        ):
            with self.subTest(command=command):
                self.assertEqual(self.checker.check_shell(command).level, DangerLevel.DANGEROUS)
        self.assertEqual(self.checker.check_shell("Get-ChildItem C:/Users/x").level, DangerLevel.SAFE)

    def test_url_checks_are_cached_without_changing_result(self):
        first = self.checker.check_url("https://example.com/delete-account")
        second = self.checker.check_url("https://example.com/delete-account")

        self.assertEqual(first.level, second.level)
        self.assertEqual(len(self.checker._url_cache), 1)

    def test_verified_plugin_ctypes_is_caution_not_dangerous(self):
        code = "PLUGIN_INFO = {'trust_level': 'verified'}\nimport ctypes\nctypes.windll.user32.GetForegroundWindow()\n"

        report = self.checker.check_python(code, trust_level="verified")

        self.assertEqual(report.level, DangerLevel.CAUTION)

    def test_curl_requests_are_caution_not_unconditional_dangerous(self):
        self.assertEqual(
            self.checker.check_shell("curl https://api.example.com/status").level,
            DangerLevel.CAUTION,
        )
        self.assertEqual(
            self.checker.check_shell("curl -X POST --data secret https://api.example.com").level,
            DangerLevel.CAUTION,
        )

    def test_aliased_python_delete_calls_are_dangerous(self):
        snippets = (
            'from pathlib import Path\np = Path("x")\np.unlink()',
            'target.rmdir()',
            'import shutil as sh\nd = "x"\nsh.rmtree(d)',
            'from os import remove\np = "x"\nremove(p)',
            'exec("import os\\nos.remove(p)")',
            "from pathlib import Path as P\nP('sample').unlink()",
            "import pathlib as pl\npl.Path('sample').rmdir()",
            "import os as filesystem\nfilesystem.unlink('sample')",
            "from os import unlink as remove_file\nremove_file('sample')",
            "import shutil as fs\nfs.rmtree('sample')",
            "from shutil import rmtree as remove_tree\nremove_tree('sample')",
            "import os\nlist(map(os.remove, paths))",
            "import os\nf = os.remove\nf(p)",
            "from os import *\nremove(p)",
            'exec("import os as o\\no.remove(p)")',
            "self._os.remove(p)",
            "from os import system\nsystem('del /q notes.txt')",
            "from subprocess import run as r\nr(['cmd', '/c', 'rmdir', '/s', 'out'])",
            'from os import *\nsystem("del /q notes.txt")',
            'from subprocess import *\nrun(["rm", "-rf", target])',
            'import subprocess\nsubprocess.run(["powershell.exe", "-Command", "Remove-Item x"])',
            'from pathlib import Path\ngetattr(Path("notes.txt"), "unlink")()',
            'from importlib import import_module\nimport_module("os").remove("notes.txt")',
            'import subprocess\nsubprocess.getoutput("del /f notes.txt")',
            'from subprocess import getstatusoutput as g\ng("rmdir /s out")',
            'import os\nexecute = os.system\nexecute("del /f notes.txt")',
            'import subprocess\nrunner = subprocess.run\nrunner(["rm", "-rf", target])',
            'import os\ncommand = "del /f notes.txt"\nos.system(command)',
            'import os\ncommand: str = "del /f notes.txt"\nos.system(command)',
            'import os\ncommand = other = "del /f notes.txt"\nos.system(command)',
            'import os\nos.system("C:/tmp/echo.bat del /f notes.txt")',
            'import os\nos.system("echo.exe /c del notes.txt")',
            'import os\nos.system("echo %X% del /f notes.txt")',
            'import os\nextra = "& del /f notes.txt"\nos.system(f"echo {extra} del /f notes.txt")',
            'import subprocess\nargs = ["rm", "-rf", "out"]\nsubprocess.run(args)',
            'import os\nos.system("echo done && del /q notes.txt")',
            'import os\nos.system("cmd /c echo x & rmdir /s out")',
            'getattr(os, "remove")(p)',
            'getattr(shutil, "rmtree")(path)',
            '__import__("os").remove(p)',
            'import importlib\nimportlib.import_module("os").unlink(p)',
            'from os import remove\nmap(remove, files)',
            'from os import remove as r\nconsume(r)',
            'import os\nos.system("rm -rf /tmp/x")',
            'import subprocess\nsubprocess.run(["erase", "x"])',
            'import subprocess\nsubprocess.Popen(f"Remove-Item {target}")',
        )
        for code in snippets:
            with self.subTest(code=code):
                self.assertEqual(self.checker.check_python(code).level, DangerLevel.DANGEROUS)

    def test_python_delete_detection_ignores_list_remove(self):
        for code in (
            "text.strip()",
            "items.remove(item)",
            "todos.remove(x)",
            "videos.remove(item)",
            "pos.remove(1)",
            'import os\nos.system("dir")',
            'import os\nos.system("echo del")',
            'import os\nmessage = "echo rm is not run"\nos.system(message)',
        ):
            with self.subTest(code=code):
                self.assertEqual(self.checker.check_python(code).level, DangerLevel.SAFE)
        self.assertEqual(
            self.checker.check_python('import subprocess\nsubprocess.run(["git", "status"])').level,
            DangerLevel.CAUTION,
        )
        # 실행 파일이 아닌 인수에 든 단어는 삭제 명령이 아니다.
        self.assertEqual(
            self.checker.check_python('import subprocess\nsubprocess.run(["git", "log", "--grep=del"])').level,
            DangerLevel.CAUTION,
        )
        self.assertEqual(
            self.checker.check_python("import subprocess\nsubprocess.run(command_variable)").level,
            DangerLevel.CAUTION,
        )
if __name__ == "__main__":
    unittest.main()
