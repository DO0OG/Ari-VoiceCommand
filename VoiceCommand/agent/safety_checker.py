"""
안전 검사기 (Safety Checker)
AI가 생성한 코드/명령/URL의 위험 수준을 분류한다.
패턴은 모듈 로드 시 한 번만 컴파일된다.
"""
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
    (_c(r'os\s*\.\s*(remove|unlink|rmdir)\s*\('),  "파일/폴더 삭제"),
    (_c(r'shutil\s*\.\s*rmtree\s*\('),             "폴더 강제 삭제"),
    (_c(r'\bctypes\b'),                             "저수준 시스템 접근"),
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
    (_c(r'\bcurl\b|\bwget\b', re.I), "외부 데이터 전송"),
]

_CAUTION_SHELL: List[_CompiledRule] = [
    (_c(r'\btaskkill\b',        re.I), "프로세스 강제 종료"),
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


class SafetyChecker:
    """코드/명령/URL의 위험 수준을 분류하는 검사기 (Phase 1.3 고도화)"""

    def __init__(self):
        self._python_cache: dict[str, SafetyReport] = {}
        self._shell_cache: dict[str, SafetyReport] = {}
        self._url_cache: dict[str, SafetyReport] = {}
        self._app_cache: dict[str, SafetyReport] = {}

    def check_python(self, code: str) -> SafetyReport:
        if code in self._python_cache:
            return self._clone_report(self._python_cache[code])
        matched = _scan(_DANGEROUS_PYTHON, code)
        if "browser_login" in code:
            matched.append("로그인 자동화")
        if any(token in code.lower() for token in _SENSITIVE_INPUT_KEYWORDS) and any(
            action in code for action in ("type_text", "write_clipboard", "press_keys")
        ):
            matched.append("민감 정보 입력 자동화")
        if matched:
            report = SafetyReport(
                level=DangerLevel.DANGEROUS,
                matched_patterns=matched,
                summary=_("위험한 파이썬 작업 감지: {matched}", matched=", ".join(matched)),
                category="web" if "로그인" in "".join(matched) else ("file_system" if "삭제" in "".join(matched) else "system")
            )
            self._python_cache[code] = report
            return self._clone_report(report)
        caution = _scan(_CAUTION_PYTHON, code)
        if any(token in code for token in ("click_image", "focus_window", "wait_for_download")):
            caution.append("상태 인식 자동화")
        if caution:
            report = SafetyReport(
                level=DangerLevel.CAUTION,
                matched_patterns=caution,
                summary=f"주의가 필요한 파이썬 작업: {', '.join(caution)}",
                category="automation" if "GUI" in "".join(caution) else "file_system"
            )
            self._python_cache[code] = report
            return self._clone_report(report)
        report = SafetyReport(level=DangerLevel.SAFE, summary="안전한 코드입니다.")
        self._python_cache[code] = report
        return self._clone_report(report)

    def check_shell(self, command: str) -> SafetyReport:
        if command in self._shell_cache:
            return self._clone_report(self._shell_cache[command])
        matched = _scan(_DANGEROUS_SHELL, command)
        if matched:
            report = SafetyReport(
                level=DangerLevel.DANGEROUS,
                matched_patterns=matched,
                summary=f"위험한 시스템 명령 감지: {', '.join(matched)}",
                category="system"
            )
            self._shell_cache[command] = report
            return self._clone_report(report)
        caution = _scan(_CAUTION_SHELL, command)
        if caution:
            report = SafetyReport(
                level=DangerLevel.CAUTION,
                matched_patterns=caution,
                summary=f"주의가 필요한 명령: {', '.join(caution)}",
                category="system"
            )
            self._shell_cache[command] = report
            return self._clone_report(report)
        report = SafetyReport(level=DangerLevel.SAFE, summary="안전한 명령입니다.")
        self._shell_cache[command] = report
        return self._clone_report(report)

    def check_url(self, url: str) -> SafetyReport:
        """URL의 안전성을 검사한다."""
        if url in self._url_cache:
            return self._clone_report(self._url_cache[url])
        url_lower = url.lower()
        blocked = [kw for kw in _BLOCKED_SITE_KEYWORDS if kw in url_lower]
        if blocked:
            report = SafetyReport(
                level=DangerLevel.DANGEROUS,
                matched_patterns=blocked,
                summary=f"민감하거나 파괴적인 웹 작업 가능성이 있는 주소입니다 ({', '.join(blocked)}).",
                category="web"
            )
            self._url_cache[url] = report
            return self._clone_report(report)
        matched = [kw for kw in _DANGEROUS_URL_KEYWORDS if kw in url_lower]
        if matched:
            report = SafetyReport(
                level=DangerLevel.DANGEROUS,
                matched_patterns=matched,
                summary=f"민감한 페이지 접근 감지 ({', '.join(matched)}). 자동화 시 보안 위험이 있습니다.",
                category="web"
            )
            self._url_cache[url] = report
            return self._clone_report(report)
        if not url_lower.startswith("https://"):
            report = SafetyReport(
                level=DangerLevel.CAUTION,
                summary="암호화되지 않은(HTTP) 사이트 접근입니다.",
                category="web"
            )
            self._url_cache[url] = report
            return self._clone_report(report)
        if any(keyword in url_lower for keyword in _TRUSTED_SITE_KEYWORDS):
            report = SafetyReport(level=DangerLevel.SAFE, summary="신뢰 정책에 포함된 사이트입니다.", category="web")
            self._url_cache[url] = report
            return self._clone_report(report)
        report = SafetyReport(level=DangerLevel.SAFE, summary="안전한 URL입니다.")
        self._url_cache[url] = report
        return self._clone_report(report)

    def check_app_launch(self, app_name: str) -> SafetyReport:
        """앱 실행의 안전성을 검사한다."""
        if app_name in self._app_cache:
            return self._clone_report(self._app_cache[app_name])
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
                summary=f"위험 앱 정책에 의해 차단된 대상입니다: {app_name}",
                category="app"
            )
            self._app_cache[app_name] = report
            return self._clone_report(report)
        if any(allowed in app_lower for allowed in _ALWAYS_ALLOWED_APPS):
            report = SafetyReport(level=DangerLevel.SAFE, summary="신뢰할 수 있는 앱입니다.")
            self._app_cache[app_name] = report
            return self._clone_report(report)
        
        report = SafetyReport(
            level=DangerLevel.CAUTION,
            summary=f"알 수 없는 외부 앱({app_name}) 실행 시도입니다.",
            category="app"
        )
        self._app_cache[app_name] = report
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
    if _checker_instance is None:
        with _checker_lock:
            if _checker_instance is None:
                _checker_instance = SafetyChecker()
    return _checker_instance
