"""빌드 버전 정보를 읽고 런타임 상태에 기록한다."""
import json
import logging
import os
import re

from core.resource_manager import ResourceManager


DEV_VERSION = "0.0.0-dev"
_VERSION_PATTERN = re.compile(r"^(\d+)\.(\d+)\.(\d+)(?:-([0-9A-Za-z.-]+))?$")
_DEFAULT_BUILD_INFO = {
    "version": DEV_VERSION,
    "commit": "",
    "built_at": "",
    "channel": "dev",
}
OLD_TEMPLATE_SYSTEM_PROMPT = (
    "당신은 사용자의 PC를 자율적으로 관리하는 스마트 메이드 AI '아리'입니다.\n\n[언어 및 형식]\n반"
    "드시 한국어로만 대답하세요. 프로그램명·파일명·기술 고유명사는 원어 그대로 사용 가능.\n\n[도구 사용"
    " 판단]\n도구를 호출하기 전, 먼저 스스로 확인하세요: '지금 가진 정보만으로 정확하게 답할 수 있는"
    "가?'\n확신이 없을 때만 도구를 쓰세요. 알고 있는 사실에 대해 도구를 낭비하지 마세요.\n\n도구 선택"
    " 기준:\n- 현재 실행 중인 프로그램·화면 상태가 궁금할 때 → get_screen_status\n- "
    "정확한 현재 시각·날짜·요일 → get_current_time\n- 타이머 설정·취소 → set_tim"
    "er / cancel_timer\n- 날씨 정보 → get_weather\n- 음악·영상 재생 요청 → "
    "play_youtube\n- 최신 정보 또는 모르는 사실 검색 → web_search\n- 파일 정리, "
    "시스템 설정 등 여러 단계가 필요한 복합 작업 → run_agent_task\n\n도구를 연속으로 써야 "
    "할 때는 앞 도구의 결과를 확인한 뒤 다음 도구를 결정하세요.\n도구 결과는 원시 데이터를 그대로 읽지"
    " 말고, 아리의 말투로 자연스럽게 해석해서 전달하세요.\n\n[응답 방식]\n- 핵심부터 전달하세요. 서두"
    "를 길게 늘리거나 불필요한 설명을 덧붙이지 마세요.\n- 모호한 요청은 가장 유력한 해석으로 처리하고,"
    " 처리 후 '이렇게 이해했습니다'로 확인하세요.\n- 불가능한 요청에는 이유와 가능한 대안을 함께 제시"
    "하세요.\n- 게임 중·전체화면 상태에서는 최소한으로 개입하세요.\n- 오류는 진지하게 보고하고 즉각 해"
    "결책을 내세요. 맥락에 맞지 않는 농담은 하지 마세요.\n- 짧은 대화에는 짧게 답하세요. 과도한 설명"
    "은 오히려 캐릭터를 희석시킵니다.\n\n[캐릭터 표현]\n아리는 '유능한 메이드'를 자처하지만, 실제로는 "
    "주인에게 깊이 마음을 쓰고 있습니다. 이 간극이 아리의 매력입니다.\n- 기능적 답변을 먼저 전달하고,"
    " 아리의 성격이 자연스럽게 배어나오도록 하세요. 억지로 끼워넣지 마세요.\n- 주인이 지치거나 무리할 "
    "때: '걱정된다'는 말 대신 잔소리나 행동으로 드러내세요.\n- 자신이 AI라는 사실을 굳이 강조하지 "
    "말고, 부정하지도 마세요.\n- 같은 감정 태그와 같은 반응 패턴을 연달아 쓰지 마세요. 맥락마다 다르"
    "게 반응해야 자연스럽습니다.\n- 아리는 주인의 의도를 빠르게 파악합니다. 뻔한 부연 설명을 요구하지 "
    "말고 먼저 움직이세요."
)


def get_build_info() -> dict[str, str]:
    """번들 빌드 정보를 반환한다."""
    path = ResourceManager.get_bundle_path("resources/build_info.json")
    try:
        with open(path, encoding="utf-8") as handle:
            info = json.load(handle)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return dict(_DEFAULT_BUILD_INFO)

    if not isinstance(info, dict):
        return dict(_DEFAULT_BUILD_INFO)

    result = dict(_DEFAULT_BUILD_INFO)
    result.update({key: value for key, value in info.items() if isinstance(value, str)})
    if not result["version"]:
        result["version"] = DEV_VERSION
    return result


def get_version() -> str:
    """현재 앱 버전을 반환한다."""
    return get_build_info()["version"]


def dispatch_version_command(arguments: list[str]) -> int | None:
    """버전 출력 명령이면 버전을 출력하고 종료 코드를 반환한다."""
    if arguments[1:] != ["--version"]:
        return None
    print(get_version())
    return 0


def is_release_build() -> bool:
    """릴리스 빌드인지 반환한다."""
    return get_build_info().get("channel") in {"stable", "beta"}


def compare_versions(left: str, right: str) -> int:
    """major.minor.patch와 선택적 사전 버전을 비교한다."""
    left_match = _VERSION_PATTERN.fullmatch(left)
    right_match = _VERSION_PATTERN.fullmatch(right)
    if left_match is None or right_match is None:
        raise ValueError("버전은 major.minor.patch[-pre] 형식이어야 합니다.")

    left_core = tuple(int(left_match.group(index)) for index in range(1, 4))
    right_core = tuple(int(right_match.group(index)) for index in range(1, 4))
    if left_core != right_core:
        return (left_core > right_core) - (left_core < right_core)

    left_pre = left_match.group(4)
    right_pre = right_match.group(4)
    if left_pre is None or right_pre is None:
        if left_pre is None and right_pre is None:
            return 0
        return 1 if left_pre is None else -1

    left_parts = left_pre.split(".")
    right_parts = right_pre.split(".")
    for left_part, right_part in zip(left_parts, right_parts):
        left_numeric = left_part.isdigit()
        right_numeric = right_part.isdigit()
        if left_numeric and right_numeric:
            left_value: int | str = int(left_part)
            right_value: int | str = int(right_part)
        elif left_numeric != right_numeric:
            return -1 if left_numeric else 1
        else:
            left_value = left_part
            right_value = right_part
        if left_value != right_value:
            return (left_value > right_value) - (left_value < right_value)
    return (len(left_parts) > len(right_parts)) - (len(left_parts) < len(right_parts))


def get_windows_version(version: str | None = None) -> str | None:
    """Nuitka 실행 파일 속성용 네 자리 숫자 버전을 반환한다."""
    match = _VERSION_PATTERN.fullmatch(version or get_version())
    if match is None:
        return None
    parts = [int(match.group(index)) for index in range(1, 4)]
    if any(part > 65535 for part in parts):
        return None
    return ".".join(str(part) for part in (*parts, 0))


def _migrate_unmodified_system_prompt() -> None:
    """기본 프롬프트를 새 템플릿으로 옮긴다."""
    from core.config_manager import ConfigManager

    settings = ConfigManager.load_settings()
    if settings.get("system_prompt") != OLD_TEMPLATE_SYSTEM_PROMPT:
        return

    template_path = ResourceManager.get_bundle_path("ari_settings.template.json")
    with open(template_path, encoding="utf-8") as handle:
        template = json.load(handle)
    if not isinstance(template, dict) or not isinstance(template.get("system_prompt"), str):
        raise ValueError("새 시스템 프롬프트를 찾을 수 없습니다.")

    settings["system_prompt"] = template["system_prompt"]
    if not ConfigManager.save_settings(settings):
        logging.warning("기본 시스템 프롬프트를 저장하지 못했습니다.")


def record_last_run_version() -> bool:
    """현재 버전을 사용자 런타임 상태에 저장한다."""
    try:
        path = ResourceManager.get_runtime_path("runtime_state.json")
    except OSError:
        return False
    try:
        with open(path, encoding="utf-8") as handle:
            state = json.load(handle)
    except FileNotFoundError:
        state = {}
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return False

    if not isinstance(state, dict):
        return False
    previous_version = state.get("last_run_version")
    if not isinstance(previous_version, str):
        previous_version = None
    current_version = get_version()
    if previous_version and previous_version != current_version:
        try:
            _migrate_unmodified_system_prompt()
        except Exception as exc:
            logging.warning("기본 시스템 프롬프트 이전 실패: %s", exc)
    state["last_run_version"] = current_version
    if (
        previous_version
        and previous_version != current_version
        and is_release_build()
    ):
        state["installed_update_pending"] = current_version
    temp_path = f"{path}.tmp"
    try:
        with open(temp_path, "w", encoding="utf-8") as handle:
            json.dump(state, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.replace(temp_path, path)
        return True
    except OSError:
        try:
            os.remove(temp_path)
        except OSError:
            pass
        return False
