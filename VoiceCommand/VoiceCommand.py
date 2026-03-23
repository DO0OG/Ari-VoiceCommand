"""core.VoiceCommand 호환 wrapper.

루트 import 경로를 유지하면서, 내부 패키지 모듈의 전역 상태까지
동적으로 위임한다.
"""

import core.VoiceCommand as _core_voicecommand
from core.VoiceCommand import *  # noqa: F401,F403


def __getattr__(name):
    return getattr(_core_voicecommand, name)


def __dir__():
    return sorted(set(globals()) | set(dir(_core_voicecommand)))
