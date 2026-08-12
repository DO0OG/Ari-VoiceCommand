"""CosyVoice3 설치 유틸."""
from __future__ import annotations

import os
import shutil
import subprocess
import venv
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
TTS_VENV_DIR = os.path.join(APP_ROOT, ".venv-tts")


def check_command(cmd: str) -> bool:
    return shutil.which(cmd) is not None


def _tts_venv_python_path() -> str:
    if os.name == "nt":
        return os.path.join(TTS_VENV_DIR, "Scripts", "python.exe")
    return os.path.join(TTS_VENV_DIR, "bin", "python")


def _ensure_tts_venv() -> str:
    python_exe = _tts_venv_python_path()
    if os.path.exists(python_exe):
        return python_exe

    venv.EnvBuilder(with_pip=True).create(TTS_VENV_DIR)
    if not os.path.exists(python_exe):
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


def download_model(model_dir: str) -> None:
    from huggingface_hub import snapshot_download

    snapshot_download(MODEL_REPO_ID, revision=MODEL_REVISION, local_dir=model_dir)


def install_cosyvoice(
    cosyvoice_dir: str,
    log: Callable[[str], None] | None = None,
    python_exe: str | None = None,
) -> str:
    logger = log or print
    target_dir = os.path.abspath(cosyvoice_dir)
    model_dir = os.path.join(target_dir, "pretrained_models", "Fun-CosyVoice3-0.5B")

    logger(_("\n설치 경로: {path}\n", path=target_dir))

    git_exe = _git_executable()
    python_exe = os.path.abspath(python_exe) if python_exe else _ensure_tts_venv()

    if not os.path.exists(target_dir):
        logger(_("[1/4] 저장소 클론 중..."))
        os.makedirs(os.path.dirname(target_dir) or ".", exist_ok=True)
        subprocess.run(
            [git_exe, "clone", "--recursive", REPO_URL, target_dir],
            check=False,
        )  # nosec B603
    else:
        logger(_("[1/4] 저장소 이미 존재: {path}", path=target_dir))

    logger(_("\n[2/4] 핵심 의존성 설치 중..."))
    subprocess.run(
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
        check=False,
    )  # nosec B603

    if not os.path.exists(model_dir):
        logger(_("\n[3/4] 모델 다운로드 중 (Fun-CosyVoice3-0.5B, 약 2GB)..."))
        download_model(model_dir)
    else:
        logger(_("\n[3/4] 모델 이미 존재: {path}", path=model_dir))

    req_file = os.path.join(target_dir, "requirements.txt")
    if os.path.exists(req_file):
        logger(_("\n[4/4] 세부 의존성 설치 중 (시간이 다소 소요될 수 있습니다)..."))
        subprocess.run(
            [python_exe, "-m", "pip", "install", "-r", req_file],
            check=False,
        )  # nosec B603
    else:
        logger(_("\n[4/4] requirements.txt 없음, 건너뜀"))

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
    return target_dir
