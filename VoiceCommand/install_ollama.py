"""Ollama 원스톱 설치 스크립트.

사용법:
  py install_ollama.py
  py install_ollama.py --models llama3.2:3b qwen3:4b
  py install_ollama.py --models-dir D:\Models\Ollama
"""
from __future__ import annotations

import argparse
import os

from core.ollama_installer import COMMON_OLLAMA_MODELS, install_ollama, normalize_models


def _parse_args():
    parser = argparse.ArgumentParser(description="Ollama 로컬 LLM 설치 스크립트")
    parser.add_argument("--install-dir", default="", help="Ollama 설치 경로 (선택)")
    parser.add_argument("--models-dir", default="", help="모델 저장 경로 (선택)")
    parser.add_argument(
        "--models",
        nargs="*",
        default=None,
        help="설치할 모델 목록 예: llama3.2:3b qwen3:4b",
    )
    return parser.parse_args()


def _prompt_models() -> list[str]:
    print("설치할 Ollama 모델을 선택하세요. 쉼표로 여러 개 선택할 수 있습니다.")
    for index, option in enumerate(COMMON_OLLAMA_MODELS, start=1):
        print(f"  {index}. {option.model:<18} - {option.summary}")
    print("  0. 모델 설치 건너뛰기")
    raw = input("번호 입력 (예: 1,2) 또는 엔터 → 1: ").strip()
    if not raw:
        return [COMMON_OLLAMA_MODELS[0].model]
    if raw == "0":
        return []

    selected: list[str] = []
    for token in raw.split(","):
        token = token.strip()
        if not token:
            continue
        try:
            idx = int(token)
        except ValueError:
            continue
        if 1 <= idx <= len(COMMON_OLLAMA_MODELS):
            selected.append(COMMON_OLLAMA_MODELS[idx - 1].model)

    custom = input("추가 모델명 입력 (없으면 엔터): ").strip()
    if custom:
        selected.extend(part.strip() for part in custom.split(","))
    return normalize_models(selected)


def install() -> None:
    args = _parse_args()
    models = normalize_models(args.models) if args.models is not None else _prompt_models()

    print("=" * 60)
    print("   Ollama 로컬 LLM 원스톱 설치")
    print("=" * 60)
    if args.install_dir:
        print(f"설치 경로: {os.path.abspath(args.install_dir)}")
    if args.models_dir:
        print(f"모델 경로: {os.path.abspath(args.models_dir)}")
    print(f"선택 모델: {', '.join(models) if models else '없음'}")
    print()

    result = install_ollama(
        install_dir=args.install_dir or None,
        models_dir=args.models_dir or None,
        models=models,
    )

    print("\n" + "=" * 60)
    print("✨ Ollama 설치가 완료되었습니다!")
    print(f"Ollama 경로: {result['install_dir']}")
    print(f"모델 경로: {result['models_dir']}")
    print(f"OpenAI 호환 주소: {result['base_url']}")
    if result["installed_models"]:
        print(f"설치 모델: {', '.join(result['installed_models'])}")
    else:
        print("설치 모델: 없음")
    print("=" * 60)


if __name__ == "__main__":
    install()
