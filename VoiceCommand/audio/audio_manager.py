"""전역 오디오 입력/출력 리소스를 공유하는 락 및 PyAudio 싱글톤."""

import logging
import threading

# 입력(마이크)과 출력(스피커)을 별도 락으로 분리
# PyAudio의 입력/출력 스트림은 독립적이므로 같은 락을 공유할 필요 없음
_audio_input_lock = threading.Lock()   # 마이크 캡처용
_audio_output_lock = threading.Lock()  # 스피커 재생용

# 하위 호환용 alias (기존 코드가 _audio_lock을 직접 임포트하는 경우 대비)
_audio_lock = _audio_input_lock


class GlobalAudio:
    """전역 PyAudio 인스턴스 관리 (싱글톤 패턴)"""
    _instance = None
    _lock = threading.Lock()

    @classmethod
    def get_instance(cls):
        """PyAudio 인스턴스를 반환 (없으면 생성)"""
        with cls._lock:
            if cls._instance is None:
                import pyaudio
                logging.info("전역 PyAudio 인스턴스 초기화 중...")
                try:
                    cls._instance = pyaudio.PyAudio()
                    logging.info("전역 PyAudio 인스턴스 생성 완료")
                except Exception as e:
                    logging.error(f"PyAudio 초기화 실패: {e}")
                    raise
            return cls._instance

    @classmethod
    def terminate(cls):
        """PyAudio 인스턴스 종료"""
        with cls._lock:
            if cls._instance:
                try:
                    cls._instance.terminate()
                    logging.info("전역 PyAudio 인스턴스 종료 완료")
                except Exception as e:
                    logging.debug(f"PyAudio 종료 오류 (무시): {e}")
                cls._instance = None


def get_audio_lock():
    """전역 오디오 입력 락 반환 (하위 호환)"""
    return _audio_input_lock


def get_audio_output_lock():
    """전역 오디오 출력 락 반환"""
    return _audio_output_lock


# ── 출력 장치 유틸리티 ─────────────────────────────────────────────────────────

# TTS는 22~24kHz mono를 재생한다. host API마다 이걸 받아주는 정도가 다르다.
#   MME/DirectSound : 임의 레이트를 알아서 리샘플 → 항상 안전
#   WASAPI          : 공유 모드에서 장치 고유 레이트(44.1/48k)만 허용 → 거부
#   WDM-KS          : 독점 커널 스트리밍 → 다른 앱이 잡고 있으면 열리지 않음
# 같은 스피커가 여러 host API로 중복 노출되므로 안전한 쪽부터 시도한다.
_HOST_API_PRIORITY = ("mme", "directsound", "wasapi", "wdm-ks")


def _get_host_api_name(pa, host_api_index: int) -> str:
    try:
        return str(pa.get_host_api_info_by_index(host_api_index).get("name", ""))
    except Exception:
        return ""


def _host_api_rank(host_api_name: str) -> int:
    lowered = (host_api_name or "").lower()
    for rank, keyword in enumerate(_HOST_API_PRIORITY):
        if keyword in lowered:
            return rank
    return len(_HOST_API_PRIORITY)


def _normalize_device_name(name: str) -> str:
    """공백과 대소문자를 무시한 비교용 키.

    같은 장치도 host API에 따라 '스피커 (Britz)' / '스피커(Britz)'처럼
    공백이 달라진다. 완전 일치로 찾으면 엉뚱한 host API가 걸린다.
    """
    return "".join((name or "").split()).lower()


def list_output_devices() -> list[dict]:
    """사용 가능한 오디오 출력 장치 목록을 반환한다.

    Returns:
        [{"index": int, "name": str, "hostApi": int, "hostApiName": str}, ...]
    """
    try:
        pa = GlobalAudio.get_instance()
        devices = []
        for i in range(pa.get_device_count()):
            info = pa.get_device_info_by_index(i)
            if info.get("maxOutputChannels", 0) > 0:
                devices.append({
                    "hostApiName": _get_host_api_name(pa, info.get("hostApi", 0)),
                    "index": i,
                    "name": info.get("name", f"Device {i}"),
                    "hostApi": info.get("hostApi", 0),
                })
        return devices
    except Exception as exc:
        logging.error("출력 장치 목록 조회 실패: %s", exc)
        return []


def get_configured_output_device_name() -> str:
    """설정에 저장된 출력 장치 이름(없으면 빈 문자열)."""
    try:
        from core.config_manager import ConfigManager
        return str(ConfigManager.get("audio_output_device", "") or "")
    except Exception as exc:
        logging.debug("출력 장치 설정 조회 실패: %s", exc)
        return ""


def get_output_device_index() -> int | None:
    """설정에 저장된 출력 장치의 PyAudio 인덱스를 반환한다.

    설정이 비어있거나 장치를 찾지 못하면 None(시스템 기본값)을 반환한다.
    """
    try:
        from core.config_manager import ConfigManager
        device_name = ConfigManager.get("audio_output_device", "")
        if not device_name:
            return None
        return _find_device_index_by_name(device_name)
    except Exception as exc:
        logging.debug("출력 장치 인덱스 조회 실패, 기본값 사용: %s", exc)
        return None


# MME는 장치 이름을 31자로 자른다. 같은 장치라도 host API마다 이름이
# 잘리거나 공백이 달라지므로 접두어 일치까지 허용한다. 8자 미만은
# 서로 다른 장치를 오인할 수 있어 접두어 매칭에서 제외한다.
_MIN_PREFIX_MATCH_CHARS = 8


def _names_refer_to_same_device(configured: str, candidate: str) -> bool:
    if not configured or not candidate:
        return False
    if configured == candidate:
        return True
    shorter, longer = sorted((configured, candidate), key=len)
    return len(shorter) >= _MIN_PREFIX_MATCH_CHARS and longer.startswith(shorter)


def find_output_device_candidates(name: str) -> list[int]:
    """설정된 이름과 같은 장치를 host API 안전 순으로 나열한다.

    같은 스피커가 MME·DirectSound·WASAPI·WDM-KS로 중복 노출되는데
    TTS의 22~24kHz mono를 받아주는 건 앞쪽 두 개뿐이다. 호출자는
    이 순서대로 스트림 개설을 시도하면 된다.
    """
    wanted = _normalize_device_name(name)
    if not wanted:
        return []

    matches = [
        device for device in list_output_devices()
        if _names_refer_to_same_device(wanted, _normalize_device_name(device["name"]))
    ]
    if not matches:
        logging.warning("출력 장치 '%s'를 찾을 수 없어 시스템 기본값 사용", name)
        return []

    matches.sort(key=lambda d: _host_api_rank(d.get("hostApiName", "")))
    return [device["index"] for device in matches]


def _find_device_index_by_name(name: str) -> int | None:
    """장치 이름으로 PyAudio 출력 장치 인덱스를 찾는다."""
    candidates = find_output_device_candidates(name)
    return candidates[0] if candidates else None

