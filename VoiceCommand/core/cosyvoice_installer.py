"""CosyVoice3 설치 유틸."""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
from typing import Callable

from i18n.translator import _


DEFAULT_COSYVOICE_DIR = os.path.join(
    os.environ.get("USERPROFILE", os.path.expanduser("~")),
    "CosyVoice",
)
REPO_URL = "https://github.com/FunAudioLLM/CosyVoice.git"
MODEL_REPO_ID = "FunAudioLLM/Fun-CosyVoice3-0.5B"
# Immutable revision pin for Bandit B615 and reproducible installs.
MODEL_REVISION = "29e01c4e8d000f4bcd70751be16fa94bf3d85a18"
APP_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LEGACY_TTS_VENV_DIR = os.path.join(APP_ROOT, ".venv-tts")
_INSTALL_STATE_PREFIX = "cosyvoice-install-v1:"
_INSTALLING_STATE_PREFIX = "cosyvoice-installing-v1:"
_DECLINED_STATE = "cosyvoice-declined-v1"
_MODEL_REQUIRED_FILES = (
    "campplus.onnx",
    "cosyvoice3.yaml",
    "flow.pt",
    "hift.pt",
    "llm.pt",
    "speech_tokenizer_v3.onnx",
)
SUPPORTED_PYTHON_VERSIONS = ((3, 11), (3, 10))


def is_valid_cosyvoice_dir(path: str) -> bool:
    """모델 폴더(pretrained_models)가 있는 CosyVoice 설치 경로인지 확인한다."""
    return bool(path) and os.path.isdir(os.path.join(path, "pretrained_models"))


def find_cosyvoice_dir(configured: str = "") -> str:
    """현재 설정, 자동 탐색 경로, 설치기 기본 경로 순으로 유효한 설치 경로를 찾는다. 없으면 빈 문자열."""
    candidates = [configured]
    try:
        from tts.cosyvoice_tts import _get_cosyvoice_dir

        candidates.append(_get_cosyvoice_dir())
    except Exception as exc:
        logging.debug("CosyVoice 자동 탐색 경로 조회 실패: %s", exc)
    candidates.append(DEFAULT_COSYVOICE_DIR)
    for candidate in candidates:
        if is_valid_cosyvoice_dir(candidate):
            return os.path.abspath(candidate)
    return ""


def check_command(cmd: str) -> bool:
    return shutil.which(cmd) is not None


def _writable_tts_venv_dir() -> str:
    from core.resource_manager import ResourceManager

    return ResourceManager.get_writable_path(".venv-tts")


def _tts_venv_python_in(directory: str) -> str:
    if os.name == "nt":
        return os.path.join(directory, "Scripts", "python.exe")
    return os.path.join(directory, "bin", "python")


def _tts_venv_python_path() -> str:
    writable_dir = _writable_tts_venv_dir()
    writable_python = _tts_venv_python_in(writable_dir)
    if os.path.isfile(writable_python):
        return writable_python

    legacy_python = _tts_venv_python_in(LEGACY_TTS_VENV_DIR)
    if os.path.isfile(legacy_python):
        return legacy_python

    return writable_python


def _python_candidates() -> list[list[str]]:
    candidates: list[list[str]] = []
    seen: set[tuple[str, tuple[str, ...]]] = set()

    def add(candidate: str | None, *args: str) -> None:
        if not candidate:
            return
        key = (os.path.normcase(os.path.abspath(candidate)), args)
        if key not in seen:
            seen.add(key)
            candidates.append([candidate, *args])

    launchers = [shutil.which("py")]
    launchers.extend(
        os.path.join(root, *parts)
        for root, parts in (
            (os.environ.get("SystemRoot", r"C:\Windows"), ("py.exe",)),
            (os.environ.get("LOCALAPPDATA", ""), ("Programs", "Python", "Launcher", "py.exe")),
        )
        if root
    )
    for launcher in launchers:
        if launcher and (launcher == launchers[0] or os.path.isfile(launcher)):
            for version in SUPPORTED_PYTHON_VERSIONS:
                add(launcher, f"-3.{version[1]}")

    for command in ("python", "python3"):
        add(shutil.which(command))

    if os.name == "nt":
        try:
            import winreg

            for hive, key_path in (
                (winreg.HKEY_CURRENT_USER, "Environment"),
                (winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment"),
            ):
                try:
                    with winreg.OpenKey(hive, key_path) as key:
                        value = winreg.QueryValueEx(key, "Path")[0]
                    for directory in os.path.expandvars(str(value)).split(os.pathsep):
                        candidate = os.path.join(directory, "python.exe")
                        if directory and os.path.isfile(candidate):
                            add(candidate)
                except OSError:
                    continue
        except ImportError:
            pass

    local_app_data = os.environ.get("LOCALAPPDATA", "")
    program_files = os.environ.get("ProgramFiles", "")
    for root, folder in (
        (local_app_data, "Programs\\Python\\Python311"),
        (local_app_data, "Programs\\Python\\Python310"),
        (program_files, "Python311"),
        (program_files, "Python310"),
        ("C:\\", "Python311"),
        ("C:\\", "Python310"),
    ):
        if root:
            candidate = os.path.join(root, folder, "python.exe")
            if os.path.isfile(candidate):
                add(candidate)
    return candidates


def _inspect_python(candidate: list[str]) -> tuple[str, tuple[int, int], bool] | None:
    code = (
        "import struct,sys; "
        "print('ARI_PYTHON=' + sys.executable + '|' + str(sys.version_info[0]) + '.' + "
        "str(sys.version_info[1]) + '|' + str(struct.calcsize('P') * 8))"
    )
    env = os.environ.copy()
    env.pop("PYTHONHOME", None)
    env.pop("PYTHONPATH", None)
    # 버전 확인만 하는 실행이 py 런처의 자동 설치를 시작하지 않게 한다.
    env["PYTHON_MANAGER_AUTOMATIC_INSTALL"] = "false"
    env.pop("PYLAUNCHER_ALLOW_INSTALL", None)
    env.pop("PYLAUNCHER_ALWAYS_INSTALL", None)
    try:
        result = subprocess.run(
            [*candidate, "-c", code],
            check=False,
            capture_output=True,
            text=True,
            errors="replace",
            timeout=10,
            env=env,
            **({"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}),
        )  # nosec B603
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    for line in result.stdout.splitlines():
        if line.startswith("ARI_PYTHON="):
            try:
                executable, version, bits = line.removeprefix("ARI_PYTHON=").rsplit("|", 2)
                major, minor = (int(part) for part in version.split("."))
                return executable, (major, minor), bits == "64"
            except (ValueError, TypeError):
                return None
    return None


def _base_python_executable() -> str:
    from core.resource_manager import is_bundled

    if not is_bundled():
        return sys.executable

    found_versions: set[tuple[int, int]] = set()
    supported: dict[tuple[int, int], str] = {}
    for candidate in _python_candidates():
        inspected = _inspect_python(candidate)
        if inspected is None:
            continue
        executable, version, is_64_bit = inspected
        found_versions.add(version)
        if is_64_bit and version in SUPPORTED_PYTHON_VERSIONS:
            supported.setdefault(version, executable)
    for version in SUPPORTED_PYTHON_VERSIONS:
        if version in supported:
            return supported[version]

    if found_versions:
        versions = ", ".join(f"{major}.{minor}" for major, minor in sorted(found_versions))
        raise RuntimeError(
            _(
                "지원되지 않는 Python 버전 {versions}을(를) 찾았습니다. CosyVoice에는 Python 3.10 또는 3.11(64비트)이 필요합니다. 기존 Python을 제거할 필요 없이 해당 버전을 추가로 설치해 주세요.",
                versions=versions,
            )
        )
    raise RuntimeError(
        _("Python을 찾지 못했습니다. Python 3.10 또는 3.11(64비트)을 설치한 뒤 다시 시도해 주세요.")
    )


def _create_tts_venv(venv_dir: str, base_python: str, logger: Callable[[str], None]) -> None:
    logger(_("CosyVoice 전용 가상환경을 만드는 중입니다..."))
    try:
        result = subprocess.run(
            [base_python, "-m", "venv", venv_dir],
            check=False,
        )  # nosec B603
    except Exception as exc:
        message = _(
            "CosyVoice 전용 가상환경을 만들지 못했습니다: {error}",
            error=exc,
        )
        logger(message)
        raise RuntimeError(message) from exc

    if result.returncode != 0:
        message = _(
            "CosyVoice 전용 가상환경을 만들지 못했습니다 (종료 코드: {returncode})",
            returncode=result.returncode,
        )
        logger(message)
        raise RuntimeError(message)


def _ensure_tts_venv() -> str:
    python_exe = _tts_venv_python_path()
    if os.path.isfile(python_exe):
        return python_exe

    venv_dir = os.path.dirname(os.path.dirname(python_exe))
    _create_tts_venv(venv_dir, _base_python_executable(), logging.info)
    if not os.path.isfile(python_exe):
        raise RuntimeError(
            _(
                "CosyVoice 전용 가상환경 Python을 찾지 못했습니다: {python_exe}",
                python_exe=python_exe,
            )
        )
    return python_exe


def _git_executable() -> str:
    candidate = shutil.which("git")
    if not candidate:
        raise RuntimeError(_("Git이 설치되어 있지 않습니다. (https://git-scm.com)"))
    return candidate


def _is_complete_model(model_dir: str) -> bool:
    return all(
        os.path.isfile(os.path.join(model_dir, name))
        and os.path.getsize(os.path.join(model_dir, name)) > 0
        for name in _MODEL_REQUIRED_FILES
    )


def _run_checked(command: list[str], step: str, logger: Callable[[str], None]) -> None:
    try:
        result = subprocess.run(command, check=False)
    except Exception as exc:
        message = _(
            "CosyVoice 설치 단계에 실패했습니다: {step} ({error})",
            step=step,
            error=exc,
        )
        logger(message)
        raise RuntimeError(message) from exc

    if result.returncode != 0:
        message = _(
            "CosyVoice 설치 단계에 실패했습니다: {step} (종료 코드: {returncode})",
            step=step,
            returncode=result.returncode,
        )
        logger(message)
        raise RuntimeError(message)


def _install_state_path() -> str:
    from core.resource_manager import ResourceManager

    return ResourceManager.get_writable_path(".cosyvoice_asked")


def _write_install_state(state: str, flag_file: str | None = None) -> None:
    state_path = flag_file or _install_state_path()
    os.makedirs(os.path.dirname(state_path), exist_ok=True)
    with open(state_path, "w", encoding="utf-8") as state_file:
        state_file.write(state)


def mark_cosyvoice_install_started(cosyvoice_dir: str, flag_file: str | None = None) -> None:
    _write_install_state(_INSTALLING_STATE_PREFIX + os.path.abspath(cosyvoice_dir), flag_file)


def mark_cosyvoice_install_complete(cosyvoice_dir: str, flag_file: str | None = None) -> bool:
    """완전한 모델이 설치된 경우에만 첫 실행 안내 완료를 기록한다."""
    if not is_cosyvoice_model_installed(cosyvoice_dir):
        return False
    _write_install_state(_INSTALL_STATE_PREFIX + os.path.abspath(cosyvoice_dir), flag_file)
    return True


def mark_cosyvoice_prompt_declined(flag_file: str | None = None) -> None:
    _write_install_state(_DECLINED_STATE, flag_file)


def is_cosyvoice_install_recorded(flag_file: str, configured_dir: str = "") -> bool:
    """첫 실행 안내를 건너뛸지 판단한다. 설치를 시작했지만 끝나지 않은 상태만 다시 안내한다."""
    try:
        with open(flag_file, "r", encoding="utf-8") as state_file:
            state = state_file.read().strip()
    except OSError:
        return bool(configured_dir) and os.path.isdir(configured_dir)
    return not state.startswith(_INSTALLING_STATE_PREFIX)


def download_model(model_dir: str) -> None:
    from huggingface_hub import snapshot_download

    os.makedirs(model_dir, exist_ok=True)
    snapshot_download(MODEL_REPO_ID, revision=MODEL_REVISION, local_dir=model_dir)
    if not _is_complete_model(model_dir):
        raise RuntimeError(_("CosyVoice 모델 파일이 모두 다운로드되지 않았습니다. 다시 설치해 주세요."))


def is_cosyvoice_model_installed(cosyvoice_dir: str) -> bool:
    model_dir = os.path.join(cosyvoice_dir, "pretrained_models", "Fun-CosyVoice3-0.5B")
    return _is_complete_model(model_dir)


def install_cosyvoice(
    cosyvoice_dir: str,
    log: Callable[[str], None] | None = None,
    python_exe: str | None = None,
) -> str:
    logger = log or print
    target_dir = os.path.abspath(cosyvoice_dir)
    model_dir = os.path.join(target_dir, "pretrained_models", "Fun-CosyVoice3-0.5B")

    logger(_("\n설치 경로: {path}\n", path=target_dir))
    mark_cosyvoice_install_started(target_dir)

    git_exe = _git_executable()
    python_exe = os.path.abspath(python_exe) if python_exe else _ensure_tts_venv()

    if not os.path.exists(target_dir):
        logger(_("[1/4] 저장소 클론 중..."))
        os.makedirs(os.path.dirname(target_dir) or ".", exist_ok=True)
        _run_checked(
            [git_exe, "clone", "--recursive", REPO_URL, target_dir],
            _("저장소 클론"),
            logger,
        )  # nosec B603
    else:
        logger(_("[1/4] 저장소 이미 존재: {path}", path=target_dir))

    req_file = os.path.join(target_dir, "requirements.txt")
    if not os.path.exists(req_file):
        message = _(
            "CosyVoice 저장소가 완전하지 않습니다. requirements.txt가 없어 설치를 계속할 수 없습니다."
        )
        logger(message)
        raise RuntimeError(message)

    logger(_("\n[2/4] 핵심 의존성 설치 중..."))
    _run_checked(
        [
            python_exe,
            "-m",
            "pip",
            "install",
            "huggingface_hub",
            "torch",
            "torchaudio",
            "--upgrade",
        ],
        _("핵심 의존성 설치"),
        logger,
    )  # nosec B603

    if not _is_complete_model(model_dir):
        logger(_("\n[3/4] 모델 다운로드 중 (Fun-CosyVoice3-0.5B, 약 2GB)..."))
        try:
            download_model(model_dir)
        except Exception as exc:
            message = _(
                "CosyVoice 설치 단계에 실패했습니다: {step} ({error})",
                step=_("모델 다운로드"),
                error=exc,
            )
            logger(message)
            raise RuntimeError(message) from exc
    else:
        logger(_("\n[3/4] 모델 이미 존재: {path}", path=model_dir))

    logger(_("\n[4/4] 세부 의존성 설치 중 (시간이 다소 소요될 수 있습니다)..."))
    _run_checked(
        [python_exe, "-m", "pip", "install", "-r", req_file],
        _("세부 의존성 설치"),
        logger,
    )  # nosec B603

    logger("\n" + "=" * 60)
    logger(_("✨ CosyVoice3 설치가 완료되었습니다!"))
    logger(_("위치: {path}", path=target_dir))
    logger("")
    logger(_("다음 단계:"))
    logger(_("  1. 아리 설정 → TTS 모드 → 로컬 (CosyVoice3) 선택"))
    logger(
        _(
            "  2. 설정 → CosyVoice 경로 → {path} 입력 (또는 자동 감지)",
            path=target_dir,
        )
    )
    logger("=" * 60)
    if not mark_cosyvoice_install_complete(target_dir):
        raise RuntimeError(_("CosyVoice 설치가 완료되지 않았습니다. 모델 파일을 확인해 주세요."))
    return target_dir
