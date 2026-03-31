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

from core.cosyvoice_installer import DEFAULT_COSYVOICE_DIR, install_cosyvoice


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
        help=f"설치 경로 (기본값: {DEFAULT_COSYVOICE_DIR})",
    )
    args, _ = parser.parse_known_args()

    if args.dir:
        return os.path.abspath(args.dir)

    # 대화형 입력
    print(f"CosyVoice3 설치 경로를 입력하세요.")
    print(f"  기본값: {DEFAULT_COSYVOICE_DIR}")
    user_input = input("경로 (엔터 → 기본값 사용): ").strip()
    return os.path.abspath(user_input) if user_input else DEFAULT_COSYVOICE_DIR


def install_to_path(cosyvoice_dir: str) -> str:
    return install_cosyvoice(cosyvoice_dir)


def install() -> None:
    print("=" * 60)
    print("   CosyVoice3 로컬 TTS 엔진 원스톱 설치")
    print("=" * 60)

    cosyvoice_dir = _parse_args()
    install_to_path(cosyvoice_dir)


if __name__ == "__main__":
    install()
