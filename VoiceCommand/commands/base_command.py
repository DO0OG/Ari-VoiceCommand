"""명령 기본 인터페이스"""
from abc import ABC, abstractmethod


class BaseCommand(ABC):
    """명령 기본 클래스"""

    @abstractmethod
    def matches(self, text: str) -> bool:
        """명령어 매칭 여부 확인"""
        pass

    @abstractmethod
    def execute(self, text: str) -> None:
        """명령 실행"""
        pass
