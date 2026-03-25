"""
Nuitka EXE 빌드 스크립트 (최적화 버전)
실행: python build_exe.py          # 증분 빌드 (캐시 재사용, 빠름)
실행: python build_exe.py --clean  # 클린 빌드 (캐시 삭제)
실행: python build_exe.py --onefile # 단일 파일 빌드 (배포용, 느림)
권장: python validate_repo.py      # 빌드 전 검증

출력: dist/Ari/

포함 모듈 (2026-03-25):
  agent/agent_orchestrator  — 병렬 실행 및 자율 반성(Reflection) 지원
  agent/agent_planner       — 플래너/실행 모델 분리, 앱 워크플로우 템플릿 확장
  agent/agent_orchestrator  — 실행 상태 기반 재계획 힌트 주입
  agent/file_tools.py       — 확장된 파일 작업군 (이름 변경, 병합, 정리, 분석, 로그 리포트)
  agent/proactive_scheduler — 주제 기반 선제 제안 및 지정 시각 알람
  agent/real_verifier.py    — 창/URL/이미지/workflow JSON 기반 실제 상태 검증 강화
  agent/execution_analysis.py — 경로/상태 기반 의존성 분석
  commands/ai_command.py     — 도구 호출 누락 시 복합 요청 자동 승격 + 예약 종료 안전 가드
  services/web_tools.py      — 브라우저 셀렉터/액션 전략 지속 메모리 + goal_hint 재사용 + wait_url/wait_title/wait_selector/read_url 상태 적응
  agent/automation_helpers.py — 데스크톱 창 타깃/워크플로우 기억 + 유사 goal_hint 재사용 + 풍부한 데스크톱 액션 + wait_image
  agent/strategy_memory.py    — workflow hint 축적 및 재사용
  agent/agent_planner.py      — 메모장/탐색기/브라우저/VS Code/계산기 앱 워크플로우 템플릿
  agent/autonomous_executor.py — 메인/runner 공통 adaptive/resilient workflow + 상태 기반 자동 보강 + planning snapshot 노출
  core/plugin_loader.py      — 사용자 플러그인 로더 및 확장 진입점
  ui/theme.py, ui/common.py — `%AppData%/Ari/theme/*.json` 기반 UI 테마 시스템
  plugins/sample_plugin.py   — 사용자 플러그인 템플릿
  tts/cosyvoice_tts.py      — 로컬 TTS 워커 재사용 + 안정화된 스트리밍 출력
  ui/memory_panel.py        — 메모리 패널 통계 탭 레이아웃 보정
"""
import os
import shutil
import sys
import multiprocessing
import importlib.util
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
print("• 권장 사전 검증: python validate_repo.py\n")

try:
    from nuitka.__main__ import main as nuitka_main
except ImportError:
    raise SystemExit(
        "Nuitka가 설치되어 있지 않습니다. "
        "먼저 `python -m pip install nuitka`를 실행해 주세요."
    )

HERE = os.path.dirname(os.path.abspath(__file__))
DIST_DIR = os.path.join(HERE, "dist", "Ari")


def _module_exists(module_name: str) -> bool:
    return importlib.util.find_spec(module_name) is not None


def _optional_include_packages(*module_names: str) -> list[str]:
    args: list[str] = []
    for module_name in module_names:
        if _module_exists(module_name):
            args.append(f"--include-package={module_name}")
        else:
            print(f"• 선택 패키지 생략: {module_name}")
    return args

# 클린 빌드 처리
if clean_build and os.path.exists(os.path.join(HERE, "dist")):
    print("기존 빌드 캐시 및 출력물 삭제 중...")
    shutil.rmtree(os.path.join(HERE, "dist"))

nuitka_args = [
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
    "--include-data-dir=theme=theme",
    "--include-data-files=DNFBitBitv2.ttf=DNFBitBitv2.ttf",
    "--include-data-files=icon.png=icon.png",
    "--include-data-files=icon.ico=icon.ico",
    "--include-data-files=reference.wav=reference.wav",
    "--include-data-files=ari_settings.json=ari_settings.json",
    "--include-data-files=cosyvoice_worker.py=cosyvoice_worker.py",
    "--include-data-files=install_cosyvoice.py=install_cosyvoice.py",
    *(["--include-data-files=plugins/sample_plugin.py=plugins/sample_plugin.py"] if os.path.exists(os.path.join(HERE, "plugins", "sample_plugin.py")) else []),

    # 아이콘 설정
    *( ["--windows-icon-from-ico=icon.ico"] if os.path.exists("icon.ico") else [] ),

    # 필수 패키지 명시
    "--include-module=confirmation_manager",
    "--include-module=agent.agent_orchestrator",
    "--include-module=agent.agent_planner",
    "--include-module=agent.autonomous_executor",
    "--include-module=agent.file_tools",
    "--include-module=agent.real_verifier",
    "--include-module=agent.safety_checker",
    "--include-module=agent.scheduler",
    "--include-module=agent.proactive_scheduler",
    "--include-module=agent.strategy_memory",
    "--include-module=agent.automation_helpers",
    "--include-module=core.plugin_loader",
    "--include-module=services.web_tools",
    "--include-module=ui.theme",
    "--include-module=ui.theme_runtime",
    "--include-module=ui.common",
    # agent.scheduler는 --include-package=agent 로 자동 포함
    "--include-package=agent",
    "--include-package=assistant",
    "--include-package=audio",
    "--include-package=commands",
    "--include-package=core",
    "--include-package=memory",
    "--include-package=tts",
    "--include-package=ui",
    "--include-package=services",
    "--include-package-data=agent",
    "--include-package-data=memory",
    *_optional_include_packages(
        "pycaw",
        "comtypes",
        "groq",
        "fish_audio_sdk",
        "speech_recognition",
        "pyaudio",
        "certifi",
        "websockets",
        "pydub",
        "watchdog",
        "requests",
        "httpx",
        "psutil",
        "reportlab",
        "ddgs",
        "duckduckgo_search",
        "pyautogui",
        "pyperclip",
        "pygetwindow",
        "selenium",
        "webdriver_manager",
    ),

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

try:
    original_argv = sys.argv[:]
    try:
        sys.argv = ["nuitka", *nuitka_args]
        nuitka_main()
        build_success = True
        exit_code = 0
    finally:
        sys.argv = original_argv
except SystemExit as exc:
    exit_code = exc.code if isinstance(exc.code, int) else 1
    build_success = exit_code == 0
except Exception as exc:
    print(f"\n❌ 빌드 중 예외 발생: {exc}")
    build_success = False

if build_success:
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
    if 'exit_code' in locals():
        print(f"\n❌ 빌드 중 오류 발생 (코드: {exit_code})")
    else:
        print("\n❌ 빌드 중 오류 발생")
