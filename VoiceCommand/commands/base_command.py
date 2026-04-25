"""명령 기본 인터페이스"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class CommandResult:
    """명령 실행 결과 표준 형식."""

    success: bool
    response: str = ""
    data: dict[str, Any] | None = field(default=None)


class BaseCommand(ABC):
    """명령 기본 클래스.

    priority: 낮을수록 먼저 매칭 시도. 기본값 50.
    특수 명령(종료, 타이머 등)은 낮은 값(10~30), AI fallback은 높은 값(100).
    """
    priority: int = 50

    @abstractmethod
    def matches(self, text: str) -> bool:
        """명령어 매칭 여부 확인"""
        pass

    @abstractmethod
    def execute(self, text: str) -> CommandResult | None:
        """명령 실행"""
        pass
