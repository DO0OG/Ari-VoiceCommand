"""
안전 검사기 (Safety Checker)
AI가 생성한 코드/명령의 위험 수준을 분류합니다.
패턴은 모듈 로드 시 한 번만 컴파일됩니다.
"""
import re
from enum import Enum
from dataclasses import dataclass, field
from typing import List, Tuple


class DangerLevel(Enum):
    SAFE = "safe"
    CAUTION = "caution"
    DANGEROUS = "dangerous"


@dataclass
class SafetyReport:
    level: DangerLevel
    matched_patterns: List[str] = field(default_factory=list)
    summary_kr: str = ""


# 패턴은 (compiled_re, 한국어_설명) 튜플로 모듈 로드 시 1회 컴파일
_CompiledRule = Tuple[re.Pattern, str]

def _c(pattern: str, flags: int = 0) -> re.Pattern:
    return re.compile(pattern, flags)


_DANGEROUS_PYTHON: List[_CompiledRule] = [
    (_c(r'os\s*\.\s*(remove|unlink|rmdir)\s*\('),  "파일/폴더 삭제"),
    (_c(r'shutil\s*\.\s*rmtree\s*\('),             "폴더 강제 삭제"),
    (_c(r'\bctypes\b'),                             "저수준 시스템 접근"),
    (_c(r'win32api|win32con|winreg'),               "Windows API/레지스트리 접근"),
]

_CAUTION_PYTHON: List[_CompiledRule] = [
    (_c(r"open\s*\([^)]*['\"][^'\"]*['\"],\s*['\"]w"), "파일 쓰기"),
    (_c(r'\bsubprocess\b'),                             "외부 프로세스 실행"),
]

_DANGEROUS_SHELL: List[_CompiledRule] = [
    (_c(r'\bshutdown\b',    re.I), "컴퓨터 종료"),
    (_c(r'\bformat\s+\w:',  re.I), "디스크 포맷"),
    (_c(r'del\s+/[fFsS]',   re.I), "강제 파일 삭제"),
    (_c(r'rd\s+/[sS]',      re.I), "폴더 강제 삭제"),
    (_c(r'reg\s+delete',    re.I), "레지스트리 삭제"),
    (_c(r'netsh\s+.*firewall', re.I), "방화벽 설정 변경"),
    (_c(r'\bbcdedit\b',     re.I), "부트 설정 변경"),
    (_c(r'\bdiskpart\b',    re.I), "디스크 파티션 조작"),
]

_CAUTION_SHELL: List[_CompiledRule] = [
    (_c(r'\btaskkill\b',        re.I), "프로세스 강제 종료"),
    (_c(r'\bnet\s+user\b',      re.I), "사용자 계정 변경"),
    (_c(r'\bsc\s+(stop|start)\b', re.I), "서비스 중지/시작"),
]


def _scan(rules: List[_CompiledRule], text: str) -> List[str]:
    """일치하는 모든 규칙의 설명 목록 반환"""
    return [desc for pattern, desc in rules if pattern.search(text)]


class SafetyChecker:
    """코드/명령의 위험 수준을 분류하는 검사기"""

    def check_python(self, code: str) -> SafetyReport:
        matched = _scan(_DANGEROUS_PYTHON, code)
        if matched:
            return SafetyReport(
                level=DangerLevel.DANGEROUS,
                matched_patterns=matched,
                summary_kr=f"위험한 작업 감지: {', '.join(matched)}",
            )
        caution = _scan(_CAUTION_PYTHON, code)
        if caution:
            return SafetyReport(
                level=DangerLevel.CAUTION,
                matched_patterns=caution,
                summary_kr=f"주의가 필요한 작업: {', '.join(caution)}",
            )
        return SafetyReport(level=DangerLevel.SAFE, summary_kr="안전한 코드입니다.")

    def check_shell(self, command: str) -> SafetyReport:
        matched = _scan(_DANGEROUS_SHELL, command)
        if matched:
            return SafetyReport(
                level=DangerLevel.DANGEROUS,
                matched_patterns=matched,
                summary_kr=f"위험한 명령 감지: {', '.join(matched)}",
            )
        caution = _scan(_CAUTION_SHELL, command)
        if caution:
            return SafetyReport(
                level=DangerLevel.CAUTION,
                matched_patterns=caution,
                summary_kr=f"주의가 필요한 명령: {', '.join(caution)}",
            )
        return SafetyReport(level=DangerLevel.SAFE, summary_kr="안전한 명령입니다.")


_checker_instance: "SafetyChecker | None" = None


def get_safety_checker() -> SafetyChecker:
    global _checker_instance
    if _checker_instance is None:
        _checker_instance = SafetyChecker()
    return _checker_instance
