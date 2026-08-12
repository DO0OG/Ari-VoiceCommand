"""Install Ari dependencies into project-local virtual environments."""
from __future__ import annotations

# This bootstrap runs before dependencies are installed, so importing Ari's
# i18n package here could prevent setup from starting. Keep its messages local.
import argparse
import os
import subprocess
import sys
import venv
from pathlib import Path
from typing import Sequence


HERE = Path(__file__).resolve().parent
REQUIREMENTS = HERE / "requirements.txt"
VALIDATOR = HERE / "validate_repo.py"
MAIN_VENV = HERE / ".venv"
TTS_VENV = HERE / ".venv-tts"
TTS_PACKAGES = ("huggingface_hub", "torch", "torchaudio")


def _venv_python_path(venv_dir: Path) -> Path:
    if os.name == "nt":
        return venv_dir / "Scripts" / "python.exe"
    return venv_dir / "bin" / "python"


def _ensure_venv(venv_dir: Path) -> Path:
    python_exe = _venv_python_path(venv_dir)
    if python_exe.exists():
        print(f"기존 가상환경을 사용합니다: {venv_dir}")
        return python_exe

    print(f"가상환경을 생성합니다: {venv_dir}")
    venv.EnvBuilder(with_pip=True).create(str(venv_dir))
    if not python_exe.exists():
        raise RuntimeError(f"가상환경 Python을 찾을 수 없습니다: {python_exe}")
    return python_exe


def _run_pip(python_exe: Path, *arguments: str) -> None:
    subprocess.run(
        [str(python_exe), "-m", "pip", *arguments],
        check=True,
        cwd=str(HERE),
    )  # nosec B603


def _install_main_dependencies(python_exe: Path) -> None:
    print("메인 의존성을 설치합니다...")
    _run_pip(python_exe, "install", "--upgrade", "pip")
    _run_pip(python_exe, "install", "-r", str(REQUIREMENTS))


def _install_tts_dependencies() -> None:
    tts_python = _ensure_venv(TTS_VENV)
    print("CosyVoice3 전용 의존성을 설치합니다...")
    _run_pip(tts_python, "install", "--upgrade", "pip")
    _run_pip(tts_python, "install", "--upgrade", *TTS_PACKAGES)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Ari 의존성을 프로젝트 가상환경에 설치합니다."
    )
    parser.add_argument(
        "--with-tts",
        action="store_true",
        help=".venv-tts를 만들고 CosyVoice3 핵심 의존성도 설치합니다.",
    )
    parser.add_argument(
        "--skip-validate",
        action="store_true",
        help="설치 후 저장소 검증을 실행하지 않습니다.",
    )
    parser.add_argument(
        "--no-venv",
        action="store_true",
        help=".venv 대신 현재 Python에 설치합니다(CI용).",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if not REQUIREMENTS.exists():
        print(f"requirements.txt를 찾을 수 없습니다: {REQUIREMENTS}")
        return 1

    try:
        if args.no_venv:
            main_python = Path(sys.executable).resolve()
            print(f"현재 Python을 사용합니다: {main_python}")
        else:
            main_python = _ensure_venv(MAIN_VENV)

        _install_main_dependencies(main_python)
        if args.with_tts:
            _install_tts_dependencies()

        print("모든 패키지가 성공적으로 설치되었습니다.")
        if not args.skip_validate:
            if not VALIDATOR.exists():
                raise RuntimeError(f"검증 스크립트를 찾을 수 없습니다: {VALIDATOR}")
            print("기본 검증을 실행합니다...")
            subprocess.run(
                [str(main_python), str(VALIDATOR)],
                check=True,
                cwd=str(HERE),
            )  # nosec B603
            print("검증까지 완료되었습니다.")
    except subprocess.CalledProcessError as exc:
        print(f"명령 실행 중 오류가 발생했습니다 (종료 코드 {exc.returncode}).")
        return exc.returncode or 1
    except (OSError, RuntimeError) as exc:
        print(f"설치 중 오류가 발생했습니다: {exc}")
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
