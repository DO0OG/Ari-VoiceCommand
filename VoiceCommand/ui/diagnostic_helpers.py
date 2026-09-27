"""설정 화면의 장치 진단에 사용하는 작은 헬퍼."""
from __future__ import annotations

import logging
import math
import struct

from i18n.translator import _


def run_tts_diagnostic(
    settings: dict,
    selected_mode: str,
    output_device_name: str,
    sentence: str,
    provider_factory=None,
    is_cancelled=None,
) -> tuple[bool, str]:
    """현재 선택값으로 TTS를 실행하고 실제 선택 엔진이 동작했는지 반환한다."""
    from audio.audio_manager import output_device_override
    from tts.tts_factory import create_tts_provider

    factory = provider_factory or create_tts_provider
    provider = None
    try:
        with output_device_override(output_device_name):
            provider, actual_mode = factory(settings)
            if is_cancelled is not None and is_cancelled():
                return False, ""
            if actual_mode != selected_mode:
                return False, _(
                    "선택한 TTS 엔진을 초기화하지 못해 다른 엔진으로 전환되었습니다. 설정을 확인해 주세요."
                )
            if not provider.speak(sentence):
                return False, _("TTS 시험 재생에 실패했습니다. 설정과 출력 장치를 확인해 주세요.")
        return True, _("현재 선택한 TTS 엔진의 시험 재생이 완료되었습니다.")
    except Exception as exc:
        return False, _("TTS 시험 재생에 실패했습니다: {error}").format(error=exc)
    finally:
        _cleanup_provider(provider)


def transcribe_diagnostic_sample(audio_data, settings: dict, provider_factory=None) -> tuple[bool, str]:
    """현재 STT 설정으로 캡처한 샘플을 인식한다."""
    from core.stt_provider import create_stt_provider

    factory = provider_factory or create_stt_provider
    provider = None
    try:
        provider = factory(settings)
        text = provider.transcribe(audio_data)
        if not text or not str(text).strip():
            return False, _("음성을 인식하지 못했습니다. 다시 말씀해 주세요.")
        return True, _("인식 결과: {text}").format(text=str(text).strip())
    except Exception as exc:
        return False, _("음성 인식 시험에 실패했습니다: {error}").format(error=exc)
    finally:
        _cleanup_provider(provider)


def _cleanup_provider(provider) -> None:
    """진단용으로 만든 제공자를 정리한다. 정리 실패는 진단 결과에 영향을 주지 않는다."""
    if provider is None or not hasattr(provider, "cleanup"):
        return
    try:
        provider.cleanup()
    except Exception as exc:
        logging.debug("진단용 제공자 정리 실패: %s", exc)


def resolve_input_device_index(selected_name: str, devices: list[dict]) -> int | None:
    """저장 전 입력 장치 선택 이름을 PyAudio 입력 장치 인덱스로 변환한다."""
    if not selected_name:
        return None
    wanted = _normalize_device_name(selected_name)
    for index, device in enumerate(devices):
        if device.get("maxInputChannels", 0) > 0 and _normalize_device_name(
            str(device.get("name", ""))
        ) == wanted:
            return index
    raise ValueError(_("선택한 마이크를 찾을 수 없습니다. 장치를 다시 선택해 주세요."))


def pcm_level_percent(pcm_data: bytes) -> int:
    """16-bit little-endian PCM의 RMS 레벨을 0~100 범위로 계산한다."""
    usable_length = len(pcm_data) - len(pcm_data) % 2
    if usable_length == 0:
        return 0
    sample_count = usable_length // 2
    square_total = sum(
        sample * sample
        for (sample,) in struct.iter_unpack("<h", pcm_data[:usable_length])
    )
    rms = math.sqrt(square_total / sample_count)
    return min(100, round(rms * 100 / 32768))


def _normalize_device_name(name: str) -> str:
    return "".join(name.split()).casefold()
