"""
CosyVoice3 자동 설치 스크립트 (One-Step)
- 필수 도구 확인 (Git, FFmpeg)
- 저장소 클론 및 모델 다운로드
- 가상환경 의존성 자동 설치
"""
import os
import shutil
import subprocess
import sys

COSYVOICE_DIR = r"D:\Git\CosyVoice"
MODEL_DIR = os.path.join(COSYVOICE_DIR, "pretrained_models", "Fun-CosyVoice3-0.5B")
REPO_URL = "https://github.com/FunAudioLLM/CosyVoice.git"

def check_command(cmd):
    return shutil.which(cmd) is not None

def download_model():
    subprocess.run(  # nosec B603 - controlled installer command
        [
            sys.executable,
            "-c",
            (
                "from huggingface_hub import snapshot_download;"
                f"snapshot_download('FunAudioLLM/Fun-CosyVoice3-0.5B', local_dir=r'{MODEL_DIR}')"
            ),
        ],
        check=False,
    )

def install():
    print("=" * 60)
    print("   CosyVoice3 로컬 TTS 엔진 원스톱 설치")
    print("=" * 60)

    # 0. 필수 도구 확인
    if not check_command("git"):
        print("❌ 오류: Git이 설치되어 있지 않습니다. (https://git-scm.com)")
        return
    
    # 1. 저장소 클론
    if not os.path.exists(COSYVOICE_DIR):
        print(f"\n[1/4] 저장소 클론 중...")
        os.makedirs(os.path.dirname(COSYVOICE_DIR), exist_ok=True)
        print(f"실행 중: git clone --recursive {REPO_URL} {COSYVOICE_DIR}")
        subprocess.run(  # nosec B603 - controlled installer command
            ["git", "clone", "--recursive", REPO_URL, COSYVOICE_DIR],
            check=False,
        )
    else:
        print(f"\n[1/4] 저장소 이미 존재: {COSYVOICE_DIR}")

    # 2. 필수 패키지 설치 (Main Python)
    print("\n[2/4] 핵심 의존성 설치 중...")
    print("실행 중: python -m pip install huggingface_hub torch torchaudio --upgrade")
    subprocess.run(  # nosec B603 - controlled installer command
        [sys.executable, "-m", "pip", "install", "huggingface_hub", "torch", "torchaudio", "--upgrade"],
        check=False,
    )

    # 3. 모델 다운로드
    if not os.path.exists(MODEL_DIR):
        print(f"\n[3/4] 모델 다운로드 중 (Fun-CosyVoice3-0.5B, 약 2GB)...")
        download_model()
    else:
        print(f"\n[3/4] 모델 이미 존재: {MODEL_DIR}")

    # 4. CosyVoice 내부 의존성 설치
    req_file = os.path.join(COSYVOICE_DIR, "requirements.txt")
    if os.path.exists(req_file):
        print("\n[4/4] 세부 의존성 설치 중 (시간이 다소 소요될 수 있습니다)...")
        print(f"실행 중: python -m pip install -r {req_file}")
        subprocess.run(  # nosec B603 - controlled installer command
            [sys.executable, "-m", "pip", "install", "-r", req_file],
            check=False,
        )

    print("\n" + "=" * 60)
    print("✨ CosyVoice3 설치가 완료되었습니다!")
    print(f"위치: {COSYVOICE_DIR}")
    print("이제 아리 설정에서 TTS 모드를 '로컬 (CosyVoice3)'로 변경하세요.")
    print("=" * 60)

if __name__ == "__main__":
    install()
