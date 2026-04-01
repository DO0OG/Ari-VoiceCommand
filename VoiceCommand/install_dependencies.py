import subprocess
import sys
from pathlib import Path


HERE = Path(__file__).resolve().parent
REQUIREMENTS = HERE / "requirements.txt"
VALIDATOR = HERE / "validate_repo.py"


def main():
    print("필요한 패키지를 설치합니다...")
    if not REQUIREMENTS.exists():
        print(f"requirements.txt를 찾을 수 없습니다: {REQUIREMENTS}")
        return

    try:
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "-r", str(REQUIREMENTS)],
            check=True,
        )
    except subprocess.CalledProcessError:
        print("의존성 설치 중 오류가 발생했습니다.")
        return

    print("모든 패키지가 성공적으로 설치되었습니다.")
    if VALIDATOR.exists():
        print("기본 검증을 실행합니다...")
        try:
            subprocess.run(
                [sys.executable, str(VALIDATOR)],
                check=True,
                cwd=str(HERE),
            )
        except subprocess.CalledProcessError:
            print("검증 단계에서 오류가 발생했습니다.")
            return
        print("검증까지 완료되었습니다.")


if __name__ == "__main__":
    main()
