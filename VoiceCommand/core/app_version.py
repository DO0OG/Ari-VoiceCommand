"""빌드 버전 정보를 읽고 런타임 상태에 기록한다."""
import json
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
