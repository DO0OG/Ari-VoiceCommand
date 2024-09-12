"""
CosyVoice3 설치 스크립트
- CosyVoice 저장소 클론
- 의존성 설치
- 모델 다운로드 (Fun-CosyVoice3-0.5B)
"""
import os
import sys
import subprocess
import logging

COSYVOICE_DIR = r"D:\Git\CosyVoice"
MODEL_DIR = os.path.join(COSYVOICE_DIR, "pretrained_models", "Fun-CosyVoice3-0.5B")
REPO_URL = "https://github.com/FunAudioLLM/CosyVoice.git"


def run(cmd, cwd=None, check=True):
    print(f"  > {' '.join(cmd)}")
    return subprocess.run(cmd, cwd=cwd, check=check)


def install():
    print("=" * 50)
    print("CosyVoice3 설치 시작")
    print("=" * 50)

    # 1. 저장소 클론
    parent = os.path.dirname(COSYVOICE_DIR)
    if not os.path.exists(COSYVOICE_DIR):
        print(f"\n[1/3] CosyVoice 저장소 클론 → {COSYVOICE_DIR}")
        os.makedirs(parent, exist_ok=True)
        run(["git", "clone", "--recursive", REPO_URL, COSYVOICE_DIR])
    else:
        print(f"\n[1/3] CosyVoice 저장소 이미 존재: {COSYVOICE_DIR}")

    # 2. 의존성 설치
    req_file = os.path.join(COSYVOICE_DIR, "requirements.txt")
    if os.path.exists(req_file):
        print("\n[2/3] 의존성 설치 중...")
        run([sys.executable, "-m", "pip", "install", "-r", req_file])
    else:
        print("\n[2/3] requirements.txt 없음, 건너뜀")

    # 3. 모델 다운로드
    if not os.path.exists(MODEL_DIR):
        print(f"\n[3/3] 모델 다운로드 중 (약 2~5GB)...")
        run([sys.executable, "-m", "pip", "install", "huggingface_hub", "--quiet"])
        download_script = (
            "from huggingface_hub import snapshot_download; "
            f"snapshot_download('FunAudioLLM/Fun-CosyVoice3-0.5B', local_dir=r'{MODEL_DIR}')"
        )
        run([sys.executable, "-c", download_script])
    else:
        print(f"\n[3/3] 모델 이미 존재: {MODEL_DIR}")

    print("\n" + "=" * 50)
    print("CosyVoice3 설치 완료!")
    print("설정 → TTS 모드를 '로컬 (CosyVoice3)'으로 변경하세요.")
    print("=" * 50)


if __name__ == "__main__":
    install()
