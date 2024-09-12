"""
EXE 빌드 스크립트
실행: python build_exe.py          # 증분 빌드 (빠름)
실행: python build_exe.py --clean  # 클린 빌드 (캐시 삭제)
"""
import os
import subprocess
import sys

clean_build = "--clean" in sys.argv
print("=== Ari EXE 빌드 시작 ===")
print(f"모드: {'클린 빌드' if clean_build else '증분 빌드 (캐시 재사용)'}\n")

try:
    import PyInstaller
    print("✓ PyInstaller 설치됨")
except ImportError:
    print("PyInstaller 설치 중...")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "pyinstaller"])
    print("✓ PyInstaller 설치 완료")

HERE = os.path.dirname(os.path.abspath(__file__))

cmd = [
    "pyinstaller",
    "--onedir",
    "--windowed",
    "--name=Ari",
    *( ["--clean"] if clean_build else [] ),

    # 아이콘
    "--icon=icon.ico" if os.path.exists("icon.ico") else "",

    # 데이터 파일
    "--add-data=images;images",
    "--add-data=DNFBitBitv2.ttf;.",
    "--add-data=icon.png;.",
    "--add-data=icon.ico;.",
    "--add-data=reference.wav;.",
    "--add-data=ari_settings.json;.",
    "--add-data=wakeword_data;wakeword_data",
    "--add-data=cosyvoice_worker.py;.",
    "--add-data=install_cosyvoice.py;.",

    # 숨겨진 import
    "--hidden-import=pycaw",
    "--hidden-import=comtypes",
    "--hidden-import=groq",
    "--hidden-import=fish_audio_sdk",
    "--hidden-import=speech_recognition",
    "--hidden-import=pyaudio",
    "--hidden-import=certifi",
    "--hidden-import=websockets",
    "--hidden-import=pydub",
    "--hidden-import=pydub.playback",
    "--hidden-import=watchdog",
    "--hidden-import=watchdog.observers",
    "--hidden-import=watchdog.events",

    # 제외 모듈 (용량 절약 및 빌드 오류 방지)
    "--exclude-module=matplotlib",
    "--exclude-module=tensorflow",
    "--exclude-module=keras",
    "--exclude-module=pandas",
    "--exclude-module=pytest",
    "--exclude-module=IPython",
    "--exclude-module=PIL",
    "--exclude-module=sentry_sdk",  # Python 2 uuid.py 충돌 방지

    "Main.py"
]

# 빈 항목 제거 (icon 조건부)
cmd = [c for c in cmd if c]

print(f"\n실행 명령:\n{' '.join(cmd)}\n")
result = subprocess.run(cmd)

if result.returncode == 0:
    print("\n=== 빌드 완료 ===")
    print("실행 파일: dist/Ari/Ari.exe")
    print("\n배포 방법:")
    print("  1. dist/Ari/ 폴더 전체를 압축")
    print("  2. 사용자는 압축 해제 후 Ari.exe 실행")
    print("  3. 최초 실행 시 CosyVoice 설치 여부 선택")
else:
    print(f"\n빌드 실패 (코드 {result.returncode})")
    sys.exit(result.returncode)
