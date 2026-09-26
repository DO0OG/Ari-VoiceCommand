"""계산기 명령"""
from commands.base_command import BaseCommand
import re
import logging

_EXPRESSION = re.compile(r'(-?\d+\.?\d*)\s*([+\-*/])\s*(-?\d+\.?\d*)')


def _normalize(text: str) -> str:
    # 한글 연산자를 기호로 변환
    text = text.replace("더하기", "+").replace("플러스", "+")
    text = text.replace("빼기", "-").replace("마이너스", "-")
    text = text.replace("곱하기", "*").replace("곱", "*").replace("×", "*").replace("x", "*")
    return text.replace("나누기", "/").replace("÷", "/")


class CalculatorCommand(BaseCommand):
    """간단한 계산 명령"""

    def __init__(self, tts_func):
        self._tts = tts_func

    def matches(self, text: str) -> bool:
        # 숫자-연산자-숫자 수식이 있을 때만 받는다. "txt"의 x 같은 글자 속 기호로는 매칭하지 않는다.
        return _EXPRESSION.search(_normalize(text)) is not None

    def execute(self, text: str) -> None:
        try:
            match = _EXPRESSION.search(_normalize(text))

            if match:
                num1, op, num2 = float(match.group(1)), match.group(2), float(match.group(3))

                if op == '+':
                    result = num1 + num2
                elif op == '-':
                    result = num1 - num2
                elif op == '*':
                    result = num1 * num2
                elif op == '/':
                    if num2 == 0:
                        self._tts("0으로 나눌 수 없습니다")
                        return
                    result = num1 / num2

                # 정수면 .0 제거
                if result == int(result):
                    result = int(result)

                self._tts(f"{num1} {op} {num2}는 {result}입니다")
            else:
                self._tts("계산할 수식을 이해하지 못했습니다")

        except Exception as e:
            logging.error(f"계산 오류: {e}")
            self._tts("계산에 실패했습니다")
