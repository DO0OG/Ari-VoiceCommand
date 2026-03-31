"""CosyVoice3 설치 유틸."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from typing import Callable


DEFAULT_COSYVOICE_DIR = os.path.join(
    os.environ.get("USERPROFILE", os.path.expanduser("~")),
    "CosyVoice",
)
REPO_URL = "https://github.com/FunAudioLLM/CosyVoice.git"


def check_command(cmd: str) -> bool:
    return shutil.which(cmd) is not None


def download_model(model_dir: str) -> None:
    subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "from huggingface_hub import snapshot_download;"
                f"snapshot_download('FunAudioLLM/Fun-CosyVoice3-0.5B', local_dir=r'{model_dir}')"
            ),
        ],
        check=False,
    )


def install_cosyvoice(cosyvoice_dir: str, log: Callable[[str], None] | None = None) -> str:
    logger = log or print
    target_dir = os.path.abspath(cosyvoice_dir)
    model_dir = os.path.join(target_dir, "pretrained_models", "Fun-CosyVoice3-0.5B")

    logger(f"\n설치 경로: {target_dir}\n")

    if not check_command("git"):
        raise RuntimeError("Git이 설치되어 있지 않습니다. (https://git-scm.com)")

    if not os.path.exists(target_dir):
        logger("[1/4] 저장소 클론 중...")
        os.makedirs(os.path.dirname(target_dir) or ".", exist_ok=True)
        subprocess.run(["git", "clone", "--recursive", REPO_URL, target_dir], check=False)
    else:
        logger(f"[1/4] 저장소 이미 존재: {target_dir}")

    logger("\n[2/4] 핵심 의존성 설치 중...")
    subprocess.run(
        [sys.executable, "-m", "pip", "install", "huggingface_hub", "torch", "torchaudio", "--upgrade"],
        check=False,
    )

    if not os.path.exists(model_dir):
        logger("\n[3/4] 모델 다운로드 중 (Fun-CosyVoice3-0.5B, 약 2GB)...")
        download_model(model_dir)
    else:
        logger(f"\n[3/4] 모델 이미 존재: {model_dir}")

    req_file = os.path.join(target_dir, "requirements.txt")
    if os.path.exists(req_file):
        logger("\n[4/4] 세부 의존성 설치 중 (시간이 다소 소요될 수 있습니다)...")
        subprocess.run([sys.executable, "-m", "pip", "install", "-r", req_file], check=False)
    else:
        logger("\n[4/4] requirements.txt 없음, 건너뜀")

    logger("\n" + "=" * 60)
    logger("✨ CosyVoice3 설치가 완료되었습니다!")
    logger(f"위치: {target_dir}")
    logger("")
    logger("다음 단계:")
    logger("  1. 아리 설정 → TTS 모드 → '로컬 (CosyVoice3)' 선택")
    logger(f"  2. 설정 → CosyVoice 경로 → '{target_dir}' 입력 (또는 자동 감지)")
    logger("=" * 60)
    return target_dir
