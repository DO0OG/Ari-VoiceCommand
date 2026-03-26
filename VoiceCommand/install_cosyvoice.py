"""
CosyVoice3 자동 설치 스크립트 (One-Step)
- 설치 경로를 인자 또는 대화형 입력으로 지정 가능
- 필수 도구 확인 (Git, FFmpeg)
- 저장소 클론 및 모델 다운로드
- 가상환경 의존성 자동 설치

사용법:
  python install_cosyvoice.py                        # 대화형 경로 입력
  python install_cosyvoice.py --dir "C:\\CosyVoice"  # 경로 직접 지정
"""
import argparse
import os
import shutil
import subprocess
import sys

_DEFAULT_DIR = os.path.join(os.environ.get("USERPROFILE", os.path.expanduser("~")), "CosyVoice")
REPO_URL = "https://github.com/FunAudioLLM/CosyVoice.git"


def _parse_args() -> str:
    """설치 경로를 반환한다. --dir 인자 → 대화형 입력 → 기본값 순으로 결정."""
    parser = argparse.ArgumentParser(
        description="CosyVoice3 로컬 TTS 엔진 설치 스크립트",
        add_help=True,
    )
    parser.add_argument(
        "--dir",
        metavar="PATH",
        default=None,
        help=f"설치 경로 (기본값: {_DEFAULT_DIR})",
    )
    args, _ = parser.parse_known_args()

    if args.dir:
        return os.path.abspath(args.dir)

    # 대화형 입력
    print(f"CosyVoice3 설치 경로를 입력하세요.")
    print(f"  기본값: {_DEFAULT_DIR}")
    user_input = input("경로 (엔터 → 기본값 사용): ").strip()
    return os.path.abspath(user_input) if user_input else _DEFAULT_DIR


def check_command(cmd: str) -> bool:
    return shutil.which(cmd) is not None


def download_model(model_dir: str) -> None:
    subprocess.run(  # nosec B603 - controlled installer command
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


def install() -> None:
    print("=" * 60)
    print("   CosyVoice3 로컬 TTS 엔진 원스톱 설치")
    print("=" * 60)

    cosyvoice_dir = _parse_args()
    model_dir = os.path.join(cosyvoice_dir, "pretrained_models", "Fun-CosyVoice3-0.5B")

    print(f"\n설치 경로: {cosyvoice_dir}\n")

    # 0. 필수 도구 확인
    if not check_command("git"):
        print("❌ 오류: Git이 설치되어 있지 않습니다. (https://git-scm.com)")
        return

    # 1. 저장소 클론
    if not os.path.exists(cosyvoice_dir):
        print("[1/4] 저장소 클론 중...")
        os.makedirs(os.path.dirname(cosyvoice_dir) or ".", exist_ok=True)
        subprocess.run(  # nosec B603 - controlled installer command
            ["git", "clone", "--recursive", REPO_URL, cosyvoice_dir],
            check=False,
        )
    else:
        print(f"[1/4] 저장소 이미 존재: {cosyvoice_dir}")

    # 2. 핵심 의존성 설치
    print("\n[2/4] 핵심 의존성 설치 중...")
    subprocess.run(  # nosec B603 - controlled installer command
        [sys.executable, "-m", "pip", "install", "huggingface_hub", "torch", "torchaudio", "--upgrade"],
        check=False,
    )

    # 3. 모델 다운로드
    if not os.path.exists(model_dir):
        print("\n[3/4] 모델 다운로드 중 (Fun-CosyVoice3-0.5B, 약 2GB)...")
        download_model(model_dir)
    else:
        print(f"\n[3/4] 모델 이미 존재: {model_dir}")

    # 4. CosyVoice 내부 의존성 설치
    req_file = os.path.join(cosyvoice_dir, "requirements.txt")
    if os.path.exists(req_file):
        print("\n[4/4] 세부 의존성 설치 중 (시간이 다소 소요될 수 있습니다)...")
        subprocess.run(  # nosec B603 - controlled installer command
            [sys.executable, "-m", "pip", "install", "-r", req_file],
            check=False,
        )
    else:
        print("\n[4/4] requirements.txt 없음, 건너뜀")

    print("\n" + "=" * 60)
    print("✨ CosyVoice3 설치가 완료되었습니다!")
    print(f"위치: {cosyvoice_dir}")
    print()
    print("다음 단계:")
    print("  1. 아리 설정 → TTS 모드 → '로컬 (CosyVoice3)' 선택")
    print(f"  2. 설정 → CosyVoice 경로 → '{cosyvoice_dir}' 입력 (또는 자동 감지)")
    print("=" * 60)


if __name__ == "__main__":
    install()
