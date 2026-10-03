"""
안전 검사기 (Safety Checker)
AI가 생성한 코드/명령/URL의 위험 수준을 분류한다.
패턴은 모듈 로드 시 한 번만 컴파일된다.
"""
import ast
import re
import threading
from enum import Enum
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Tuple

from i18n.translator import _


class DangerLevel(Enum):
    SAFE = "safe"
    CAUTION = "caution"
    DANGEROUS = "dangerous"


@dataclass
class SafetyReport:
    level: DangerLevel
    matched_patterns: List[str] = field(default_factory=list)
    summary: str = ""
    category: str = "general"


# 패턴은 (compiled_re, 한국어_설명) 튜플로 모듈 로드 시 1회 컴파일
_CompiledRule = Tuple[re.Pattern, str]

def _c(pattern: str, flags: int = 0) -> re.Pattern:
    return re.compile(pattern, flags)


_DANGEROUS_PYTHON: List[_CompiledRule] = [
    # 문자열로 실행하는 코드(exec 등)와 구문 오류가 있는 코드는 AST로 잡히지 않아 본문 검색도 함께 한다.
    # 왼쪽 경계는 todos.remove(x) 같은 리스트 조작이 삭제로 오인되지 않게 한다.
    # 밑줄이나 점 뒤(self._os.remove)는 삭제일 수 있어 그대로 잡는다.
    (_c(r'(?<![A-Za-z0-9])os\s*\.\s*(remove|unlink|rmdir|removedirs)\s*\('), "파일/폴더 삭제"),
    (_c(r'(?<![A-Za-z0-9])shutil\s*\.\s*rmtree\s*\('), "폴더 강제 삭제"),
    (_c(r'ctypes\s*\.\s*(windll|cdll|CDLL|WinDLL)\s*[\.\(]'), "ctypes 저수준 DLL 로드"),
    (_c(r'ctypes\s*\.\s*cast\s*\('),                "ctypes 포인터 캐스팅"),
    (_c(r'win32api|win32con|winreg'),               "Windows API/레지스트리 접근"),
    (_c(r'requests\s*\.\s*(post|put|delete)'),      "데이터 외부 전송/수정"),
]

_CAUTION_PYTHON: List[_CompiledRule] = [
    (_c(r"open\s*\([^)]*['\"][^'\"]*['\"],\s*['\"]w"), "파일 쓰기"),
    (_c(r'\bsubprocess\b'),                             "외부 프로세스 실행"),
    (_c(r'pyautogui\s*\.\s*(click|typewrite|press)'),  "GUI 직접 제어"),
]

_DANGEROUS_SHELL: List[_CompiledRule] = [
    (_c(r'\bshutdown\b',    re.I), "컴퓨터 종료"),
    (_c(r'\blogoff\b|\btsdiscon\b', re.I), "세션 종료"),
    (_c(r'\bshutdown\b.*\b/r\b', re.I), "컴퓨터 재시작"),
    (_c(r'\bformat\s+\w:',  re.I), "디스크 포맷"),
    (_c(r'del\s+/[fFsS]',   re.I), "강제 파일 삭제"),
    (_c(r'rd\s+/[sS]',      re.I), "폴더 강제 삭제"),
    (_c(r'reg\s+delete',    re.I), "레지스트리 삭제"),
    (_c(r'netsh\s+.*firewall', re.I), "방화벽 설정 변경"),
    (_c(r'\bbcdedit\b',     re.I), "부트 설정 변경"),
    (_c(r'\bdiskpart\b',    re.I), "디스크 파티션 조작"),
    # 셸 단계는 PowerShell로 실행되므로 PowerShell 명령과 삭제 별칭도 같은 기준으로 막는다.
    (_c(r'\b(?:Remove-Item|Clear-Content)\b|(?<![\w-])(?:rm|ri|rmdir|rd|del|erase)(?![\w-])', re.I), "파일/폴더 삭제"),
    (_c(r'\bStop-Computer\b', re.I), "컴퓨터 종료"),
    (_c(r'\bRestart-Computer\b', re.I), "컴퓨터 재시작"),
    (_c(r'\b(?:Format-Volume|Clear-Disk|Initialize-Disk|Remove-Partition)\b', re.I), "디스크 포맷"),
]

_CAUTION_SHELL: List[_CompiledRule] = [
    (_c(r'\bcurl\b.*(?:--data|-d\s|-X\s+(?:POST|PUT|DELETE|PATCH)|--upload-file)', re.I), "외부 데이터 전송"),
    (_c(r'\bcurl\b|\bwget\b', re.I), "외부 URL 요청"),
    (_c(r'\btaskkill\b|\bStop-Process\b', re.I), "프로세스 강제 종료"),
    (_c(r'\bnet\s+user\b',      re.I), "사용자 계정 변경"),
    (_c(r'\bsc\s+(stop|start)\b', re.I), "서비스 중지/시작"),
]

_DANGEROUS_URL_KEYWORDS = [
    "banking", "finance", "login", "password", "reset", "delete-account", 
    "account-settings", "payment", "checkout", "transfer"
]
_SENSITIVE_INPUT_KEYWORDS = ["password", "otp", "2fa", "api_key", "인증", "비밀번호", "보안", "결제"]

_ALWAYS_ALLOWED_APPS = ["notepad", "calc", "explorer", "chrome", "msedge", "cmd", "powershell"]
_BLOCKED_APPS = ["regedit", "powershell_ise", "processhacker", "wireshark"]
_TRUSTED_SITE_KEYWORDS = ["github.com", "google.com", "naver.com", "youtube.com"]
_BLOCKED_SITE_KEYWORDS = ["bank", "payment", "wallet", "admin", "delete-account"]


def _scan(rules: List[_CompiledRule], text: str) -> List[str]:
    """일치하는 모든 규칙의 설명 목록 반환"""
    return [desc for pattern, desc in rules if pattern.search(text)]


# 셸 기호 없이 이 명령들로 시작하는 한 줄은 인수에 삭제 단어가 있어도 삭제가 아니다.
# 다른 명령을 대신 실행해 주는 명령(git, cmd, xargs 등)은 넣지 않는다.
_READ_ONLY_COMMANDS = frozenset({
    "echo", "dir", "ls", "type", "cat", "findstr", "grep", "where", "which",
    "ping", "tasklist", "ipconfig", "whoami", "hostname", "ver",
})
# %VAR%·!VAR!처럼 실행할 때 펼쳐지는 값은 볼 수 없으므로 셸 기호와 같이 취급한다.
_SHELL_META = re.compile(r"[;&|`$(){}<>%!^\r\n]")


def _is_plain_read_only_command(command: str) -> bool:
    if _SHELL_META.search(command):
        return False
    words = command.split()
    # 경로가 붙은 실행 파일(C:/tmp/echo.bat 등)은 이름이 같아도 다른 프로그램일 수 있다.
    return bool(words) and words[0].lower() in _READ_ONLY_COMMANDS


def _python_contains_delete_call(code: str) -> bool:
    try:
        tree = ast.parse(code)
    except (SyntaxError, TypeError, ValueError):
        # 구문 오류 문자열(exec 인자 등)은 정규식 판정만 적용한다.
        return any(pattern.search(code) for pattern, _desc in _DANGEROUS_PYTHON[:2])

    os_modules = {"os"}
    shutil_modules = {"shutil"}
    subprocess_modules = {"subprocess"}
    importlib_modules = {"importlib"}
    os_functions = set()
    shutil_functions = set()
    shell_functions = set()
    import_module_functions = set()
    os_shell_calls = {"system", "popen"}
    subprocess_shell_calls = {
        "run", "call", "check_call", "check_output", "Popen", "getoutput", "getstatusoutput",
    }
    shell_calls = os_shell_calls | subprocess_shell_calls
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "os":
                    os_modules.add(alias.asname or alias.name)
                elif alias.name == "shutil":
                    shutil_modules.add(alias.asname or alias.name)
                elif alias.name == "subprocess":
                    subprocess_modules.add(alias.asname or alias.name)
                elif alias.name == "importlib":
                    importlib_modules.add(alias.asname or alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module == "os":
                os_functions.update(alias.asname or alias.name for alias in node.names if alias.name in {"remove", "unlink", "rmdir", "removedirs"})
                if any(alias.name == "*" for alias in node.names):
                    os_functions.update({"remove", "unlink", "rmdir", "removedirs"})
                    shell_functions.update(os_shell_calls)
                shell_functions.update(alias.asname or alias.name for alias in node.names if alias.name in os_shell_calls)
            elif node.module == "subprocess":
                shell_functions.update(
                    alias.asname or alias.name for alias in node.names if alias.name in subprocess_shell_calls
                )
                if any(alias.name == "*" for alias in node.names):
                    shell_functions.update(subprocess_shell_calls)
            elif node.module == "importlib":
                import_module_functions.update(
                    alias.asname or alias.name for alias in node.names if alias.name == "import_module"
                )
            elif node.module == "shutil":
                shutil_functions.update(alias.asname or alias.name for alias in node.names if alias.name == "rmtree")
                if any(alias.name == "*" for alias in node.names):
                    shutil_functions.add("rmtree")

    def module_name(node):
        if isinstance(node, ast.Name):
            if node.id in os_modules:
                return "os"
            if node.id in shutil_modules:
                return "shutil"
            if node.id in subprocess_modules:
                return "subprocess"
        if isinstance(node, ast.Call) and node.args and isinstance(node.args[0], ast.Constant):
            if isinstance(node.func, ast.Name) and (
                node.func.id == "__import__" or node.func.id in import_module_functions
            ):
                return node.args[0].value
            if (isinstance(node.func, ast.Attribute) and node.func.attr == "import_module"
                    and isinstance(node.func.value, ast.Name) and node.func.value.id in importlib_modules):
                return node.args[0].value
        return None

    def shell_text(node):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return node.value
        if isinstance(node, (ast.List, ast.Tuple)) and node.elts:
            words = [
                item.value if isinstance(item, ast.Constant) and isinstance(item.value, str) else ""
                for item in node.elts
            ]
            # 목록은 셸을 거치지 않아 첫 단어만 실행 파일이다. 인수에 든 단어로는 판정하지 않는다.
            # 셸을 직접 부르는 목록은 그 뒤가 명령이다.
            if Path(words[0]).stem.lower() in {"cmd", "powershell", "pwsh", "sh", "bash"}:
                return " ".join(words[1:])
            return words[0]
        if isinstance(node, ast.JoinedStr):
            return " ".join(item.value for item in node.values if isinstance(item, ast.Constant) and isinstance(item.value, str))
        return None

    def dynamic_delete(node):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name) or node.func.id != "getattr" or len(node.args) < 2:
            return False
        if not isinstance(node.args[1], ast.Constant) or not isinstance(node.args[1].value, str):
            return False
        # 직접 호출과 같은 기준이다. unlink·rmdir·rmtree는 대상이 무엇이든(Path 등) 삭제로 본다.
        if node.args[1].value in {"unlink", "rmdir", "rmtree"}:
            return True
        return module_name(node.args[0]) == "os" and node.args[1].value in {"remove", "removedirs"}

    # 상수로 대입된 변수에 담긴 명령은 그 값으로 판정한다. 여러 번 대입되면 모두 본다.
    constant_values = {}
    # execute = os.system 처럼 변수에 담아 부르는 경우도 같은 명령 검사를 받게 한다.
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            targets = node.targets
        elif isinstance(node, (ast.AnnAssign, ast.NamedExpr)) and node.value is not None:
            targets = [node.target]
        else:
            continue
        value = node.value
        for target in targets:
            if not isinstance(target, ast.Name):
                continue
            if isinstance(value, (ast.Constant, ast.List, ast.Tuple, ast.JoinedStr)):
                constant_values.setdefault(target.id, []).append(value)
            if (
                isinstance(value, ast.Attribute)
                and module_name(value.value) in {"os", "subprocess"}
                and value.attr in shell_calls
            ) or (isinstance(value, ast.Name) and value.id in shell_functions):
                shell_functions.add(target.id)

    delete_names = os_functions | shutil_functions
    for node in ast.walk(tree):
        # 호출하지 않고 참조만 해도(map(os.remove, ...), f = os.remove) 삭제 수단이다.
        if dynamic_delete(node):
            return True
        if isinstance(node, ast.Attribute):
            target_module = module_name(node.value)
            if ((target_module == "os" and node.attr in {"remove", "unlink", "rmdir", "removedirs"})
                    or (target_module == "shutil" and node.attr == "rmtree")):
                return True
        if isinstance(node, ast.Name) and node.id in delete_names and isinstance(node.ctx, ast.Load):
            return True
        if not isinstance(node, ast.Call):
            continue
        function = node.func
        if dynamic_delete(function):
            return True
        if (
            isinstance(function, ast.Name)
            and function.id in {"exec", "eval", "compile"}
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
            and _python_contains_delete_call(node.args[0].value)
        ):
            return True
        if isinstance(function, ast.Attribute):
            if function.attr in {"unlink", "rmdir", "rmtree"}:
                return True
            target_module = module_name(function.value)
            if ((target_module == "os" and function.attr in {"remove", "unlink", "rmdir", "removedirs"})
                    or (target_module == "shutil" and function.attr == "rmtree")):
                return True
            shell_call = target_module in {"os", "subprocess"} and function.attr in shell_calls
        else:
            shell_call = isinstance(function, ast.Name) and function.id in shell_functions
        if shell_call:
            # 볼 수 있는 상수 명령만 판정한다. 변수는 상수로 대입된 값이 있을 때만 그 값으로 본다.
            command_arg = node.args[0] if node.args else next(
                (keyword.value for keyword in node.keywords if keyword.arg in {"args", "cmd"}), None
            )
            if isinstance(command_arg, ast.Name):
                candidates = constant_values.get(command_arg.id, [])
            else:
                candidates = [] if command_arg is None else [command_arg]
            for candidate in candidates:
                command = shell_text(candidate)
                # 읽기 전용 예외는 전체가 보이는 문자열에만 준다. f-string의 변수 자리는 무엇이든 될 수 있다.
                whole = isinstance(candidate, ast.Constant)
                if (
                    command is not None
                    and not (whole and _is_plain_read_only_command(command))
                    and any(pattern.search(command) for pattern, _label in _DANGEROUS_SHELL)
                ):
                    return True
    return False


def _translate_matches(items: List[str]) -> List[str]:
    return [_(item) for item in items]


class SafetyChecker:
    """코드/명령/URL의 위험 수준을 분류하는 검사기 (Phase 1.3 고도화)"""

    def __init__(self):
        self._python_cache: dict[str, SafetyReport] = {}
        self._shell_cache: dict[str, SafetyReport] = {}
        self._url_cache: dict[str, SafetyReport] = {}
        self._app_cache: dict[str, SafetyReport] = {}
        self._cache_lock = threading.Lock()

    def check_python(self, code: str, trust_level: str = "") -> SafetyReport:
        cache_key = f"{trust_level}\0{code}"
        cached = self._get_cached(self._python_cache, cache_key)
        if cached is not None:
            return cached
        matched = _scan(_DANGEROUS_PYTHON, code)
        if _python_contains_delete_call(code) and "파일/폴더 삭제" not in matched:
            matched.append("파일/폴더 삭제")
        caution_from_trust: List[str] = []
        if str(trust_level or "").casefold() == "verified":
            trusted_ctypes = {"저수준 시스템 접근", "ctypes 저수준 DLL 로드", "ctypes 포인터 캐스팅"}
            downgraded = [item for item in matched if item in trusted_ctypes]
            if downgraded:
                matched = [item for item in matched if item not in trusted_ctypes]
                caution_from_trust.extend(downgraded)
        if "browser_login" in code:
            matched.append("로그인 자동화")
        if any(token in code.lower() for token in _SENSITIVE_INPUT_KEYWORDS) and any(
            action in code for action in ("type_text", "write_clipboard", "press_keys")
        ):
            matched.append("민감 정보 입력 자동화")
        if matched:
            translated = _translate_matches(matched)
            report = SafetyReport(
                level=DangerLevel.DANGEROUS,
                matched_patterns=translated,
                summary=_("위험한 파이썬 작업 감지: {matched}", matched=", ".join(translated)),
                category="web" if "로그인" in "".join(matched) else ("file_system" if "삭제" in "".join(matched) else "system")
            )
            return self._store_and_clone(self._python_cache, cache_key, report)
        caution = _scan(_CAUTION_PYTHON, code) + caution_from_trust
        if any(token in code for token in ("click_image", "focus_window", "wait_for_download")):
            caution.append("상태 인식 자동화")
        if caution:
            translated = _translate_matches(caution)
            report = SafetyReport(
                level=DangerLevel.CAUTION,
                matched_patterns=translated,
                summary=_("주의가 필요한 파이썬 작업: {matched}", matched=", ".join(translated)),
                category="automation" if "GUI" in "".join(caution) else "file_system"
            )
            return self._store_and_clone(self._python_cache, cache_key, report)
        report = SafetyReport(level=DangerLevel.SAFE, summary=_("안전한 코드입니다."))
        return self._store_and_clone(self._python_cache, cache_key, report)

    def check_shell(self, command: str) -> SafetyReport:
        cached = self._get_cached(self._shell_cache, command)
        if cached is not None:
            return cached
        matched = _scan(_DANGEROUS_SHELL, command)
        if matched:
            translated = _translate_matches(matched)
            report = SafetyReport(
                level=DangerLevel.DANGEROUS,
                matched_patterns=translated,
                summary=_("위험한 시스템 명령 감지: {matched}", matched=", ".join(translated)),
                category="system"
            )
            return self._store_and_clone(self._shell_cache, command, report)
        caution = _scan(_CAUTION_SHELL, command)
        if caution:
            translated = _translate_matches(caution)
            report = SafetyReport(
                level=DangerLevel.CAUTION,
                matched_patterns=translated,
                summary=_("주의가 필요한 명령: {matched}", matched=", ".join(translated)),
                category="system"
            )
            return self._store_and_clone(self._shell_cache, command, report)
        report = SafetyReport(level=DangerLevel.SAFE, summary=_("안전한 명령입니다."))
        return self._store_and_clone(self._shell_cache, command, report)

    def check_url(self, url: str) -> SafetyReport:
        """URL의 안전성을 검사한다."""
        cached = self._get_cached(self._url_cache, url)
        if cached is not None:
            return cached
        url_lower = url.lower()
        blocked = [kw for kw in _BLOCKED_SITE_KEYWORDS if kw in url_lower]
        if blocked:
            report = SafetyReport(
                level=DangerLevel.DANGEROUS,
                matched_patterns=blocked,
                summary=_("민감하거나 파괴적인 웹 작업 가능성이 있는 주소입니다 ({blocked}).", blocked=", ".join(blocked)),
                category="web"
            )
            return self._store_and_clone(self._url_cache, url, report)
        matched = [kw for kw in _DANGEROUS_URL_KEYWORDS if kw in url_lower]
        if matched:
            report = SafetyReport(
                level=DangerLevel.DANGEROUS,
                matched_patterns=matched,
                summary=_("민감한 페이지 접근 감지 ({matched}). 자동화 시 보안 위험이 있습니다.", matched=", ".join(matched)),
                category="web"
            )
            return self._store_and_clone(self._url_cache, url, report)
        if not url_lower.startswith("https://"):
            report = SafetyReport(
                level=DangerLevel.CAUTION,
                summary=_("암호화되지 않은(HTTP) 사이트 접근입니다."),
                category="web"
            )
            return self._store_and_clone(self._url_cache, url, report)
        if any(keyword in url_lower for keyword in _TRUSTED_SITE_KEYWORDS):
            report = SafetyReport(level=DangerLevel.SAFE, summary=_("신뢰 정책에 포함된 사이트입니다."), category="web")
            return self._store_and_clone(self._url_cache, url, report)
        report = SafetyReport(level=DangerLevel.SAFE, summary=_("안전한 URL입니다."))
        return self._store_and_clone(self._url_cache, url, report)

    def check_app_launch(self, app_name: str) -> SafetyReport:
        """앱 실행의 안전성을 검사한다."""
        cached = self._get_cached(self._app_cache, app_name)
        if cached is not None:
            return cached
        # Path.resolve() 기반 정규화로 대소문자/유니코드 우회 방지
        try:
            resolved_stem = Path(app_name).resolve().stem.lower()
        except (OSError, ValueError):
            resolved_stem = ""
        app_lower = app_name.lower()
        normalized = resolved_stem or app_lower
        if any(blocked in normalized for blocked in _BLOCKED_APPS):
            report = SafetyReport(
                level=DangerLevel.DANGEROUS,
                summary=_("위험 앱 정책에 의해 차단된 대상입니다: {app}", app=app_name),
                category="app"
            )
            return self._store_and_clone(self._app_cache, app_name, report)
        if any(allowed in app_lower for allowed in _ALWAYS_ALLOWED_APPS):
            report = SafetyReport(level=DangerLevel.SAFE, summary=_("신뢰할 수 있는 앱입니다."))
            return self._store_and_clone(self._app_cache, app_name, report)
        
        report = SafetyReport(
            level=DangerLevel.CAUTION,
            summary=_("알 수 없는 외부 앱({app}) 실행 시도입니다.", app=app_name),
            category="app"
        )
        return self._store_and_clone(self._app_cache, app_name, report)

    def _get_cached(self, cache: dict[str, SafetyReport], key: str) -> SafetyReport | None:
        with self._cache_lock:
            report = cache.get(key)
        return self._clone_report(report) if report is not None else None

    def _store_and_clone(self, cache: dict[str, SafetyReport], key: str, report: SafetyReport) -> SafetyReport:
        with self._cache_lock:
            cache[key] = report
        return self._clone_report(report)

    def _clone_report(self, report: SafetyReport) -> SafetyReport:
        return SafetyReport(
            level=report.level,
            matched_patterns=list(report.matched_patterns),
            summary=report.summary,
            category=report.category,
        )


_checker_instance: "SafetyChecker | None" = None
_checker_lock = threading.Lock()


def get_safety_checker() -> SafetyChecker:
    global _checker_instance
    with _checker_lock:
        if _checker_instance is None:
            _checker_instance = SafetyChecker()
    return _checker_instance
