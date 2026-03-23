"""
Nuitka EXE 빌드 스크립트 (최적화 버전)
실행: python build_exe.py          # 증분 빌드 (캐시 재사용, 빠름)
실행: python build_exe.py --clean  # 클린 빌드 (캐시 삭제)
실행: python build_exe.py --onefile # 단일 파일 빌드 (배포용, 느림)

출력: dist/Ari/
"""
import os
import shutil
import subprocess
import sys
import multiprocessing
from datetime import datetime

# 표준 출력 인코딩 설정 (Windows/GitHub Actions 환경 대응)
if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except AttributeError:
        pass

clean_build = "--clean" in sys.argv
one_file = "--onefile" in sys.argv
jobs = multiprocessing.cpu_count()

print("=" * 60)
print("   Ari EXE 최적화 빌드 시스템 (Nuitka)")
print("=" * 60)
print(f"• 빌드 모드: {'단일 파일' if one_file else '폴더 독립형'}")
print(f"• 작업 유형: {'클린 빌드' if clean_build else '증분 빌드'}")
print(f"• 병렬 작업: {jobs} 코어 사용\n")

try:
    import nuitka
except ImportError:
    print("Nuitka 설치 중...")
    subprocess.run(  # nosec B603 - controlled build dependency install
        [sys.executable, "-m", "pip", "install", "nuitka"],
        check=True,
    )

HERE = os.path.dirname(os.path.abspath(__file__))
DIST_DIR = os.path.join(HERE, "dist", "Ari")

# 클린 빌드 처리
if clean_build and os.path.exists(os.path.join(HERE, "dist")):
    print("기존 빌드 캐시 및 출력물 삭제 중...")
    shutil.rmtree(os.path.join(HERE, "dist"))

cmd = [
    sys.executable, "-m", "nuitka",
    "--standalone" if not one_file else "--onefile",
    f"--jobs={jobs}",
    "--windows-console-mode=disable",
    "--output-filename=Ari",
    "--output-dir=dist",
    "--show-progress",
    "--remove-output", # 빌드 완료 후 중간 파일 삭제
    "--assume-yes-for-downloads", # 자동 다운로드 승인 (비대화형 환경 대응)

    # PySide6 최적화
    "--enable-plugin=pyside6",
    "--include-qt-plugins=multimedia",

    # 데이터 자원 포함
    "--include-data-dir=images=images",
    "--include-data-files=DNFBitBitv2.ttf=DNFBitBitv2.ttf",
    "--include-data-files=icon.png=icon.png",
    "--include-data-files=icon.ico=icon.ico",
    "--include-data-files=reference.wav=reference.wav",
    "--include-data-files=ari_settings.json=ari_settings.json",
    "--include-data-files=cosyvoice_worker.py=cosyvoice_worker.py",
    "--include-data-files=install_cosyvoice.py=install_cosyvoice.py",

    # 아이콘 설정
    *( ["--windows-icon-from-ico=icon.ico"] if os.path.exists("icon.ico") else [] ),

    # 필수 패키지 명시
    "--include-module=confirmation_manager",
    "--include-module=agent_orchestrator",
    "--include-module=agent_planner",
    "--include-module=autonomous_executor",
    "--include-module=proactive_scheduler",
    "--include-module=real_verifier",
    "--include-module=safety_checker",
    "--include-module=strategy_memory",
    "--include-module=web_tools",
    "--include-module=automation_helpers",
    "--include-package=agent",
    "--include-package=assistant",
    "--include-package=audio",
    "--include-package=core",
    "--include-package=memory",
    "--include-package=tts",
    "--include-package=ui",
    "--include-package=services",
    "--include-package=pycaw",
    "--include-package=comtypes",
    "--include-package=groq",
    "--include-package=fish_audio_sdk",
    "--include-package=speech_recognition",
    "--include-package=pyaudio",
    "--include-package=certifi",
    "--include-package=websockets",
    "--include-package=pydub",
    "--include-package=watchdog",
    "--include-package=requests",
    "--include-package=httpx",
    "--include-package=psutil",
    "--include-package=reportlab",
    "--include-package=ddgs",
    "--include-package=duckduckgo_search",
    "--include-package=pyautogui",
    "--include-package=pyperclip",
    "--include-package=pygetwindow",
    "--include-package=selenium",
    "--include-package=webdriver_manager",

    # 불필요한 모듈 제외 (빌드 속도 및 용량 최적화)
    "--nofollow-import-to=matplotlib",
    "--nofollow-import-to=tensorflow",
    "--nofollow-import-to=pandas",
    "--nofollow-import-to=numpy.distutils",
    "--nofollow-import-to=pytest",
    "--nofollow-import-to=IPython",
    "--nofollow-import-to=PIL",
    
    "Main.py"
]

start_time = datetime.now().strftime("%H:%M:%S")
print(f"빌드 시작 시간: {start_time}")
result = subprocess.run(cmd, check=False)  # nosec B603 - controlled build command

if result.returncode == 0:
    # 폴더 정리
    NUITKA_OUT = os.path.join(HERE, "dist", "Main.dist")
    if not one_file and os.path.exists(NUITKA_OUT):
        if os.path.exists(DIST_DIR): shutil.rmtree(DIST_DIR)
        os.rename(NUITKA_OUT, DIST_DIR)
        print(f"\n✓ 출력 완료: {DIST_DIR}")
    
    print("\n" + "=" * 60)
    print("   빌드 성공! 배포 준비가 완료되었습니다.")
    print("=" * 60)
else:
    print(f"\n❌ 빌드 중 오류 발생 (코드: {result.returncode})")
