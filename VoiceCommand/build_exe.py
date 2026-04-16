"""
Nuitka EXE 빌드 스크립트 (최적화 버전)
실행: py -3.11 build_exe.py           # 증분 빌드 (캐시 재사용, 빠름)
실행: py -3.11 build_exe.py --clean   # 클린 빌드 (캐시 삭제)
실행: py -3.11 build_exe.py --onefile # 단일 파일 빌드 (배포용, 느림)
권장: py -3.11 validate_repo.py       # 빌드 전 검증

nofollow 정책:
  numpy, torch 등 C/Rust 확장 패키지 및 groq/openai/anthropic 등 pydantic-v2 기반
  API 클라이언트는 --nofollow-import-to 처리. 런타임에 site-packages에서 직접 로드됨.

출력: dist/Ari/

포함 모듈 (2026-04-14 최신):
  agent/agent_orchestrator.py — shared context 캐시, 동적 계획 반복, 반복 실패 조기 종료
  agent/execution_engine.py   — 반복 동일 오류 중단, 회복 전략 다변화, 단계 타임아웃 힌트
  agent/agent_planner.py      — StrategyMemory lift 게이팅 + optional step 필드 전달
  agent/agent_math.py         — cosine_similarity 공통 유틸
  agent/tag_keywords.py       — 공통 TAG_KEYWORDS 사전
  agent/record_store.py       — append-only 기반 증분 저장 스토어 스캐폴드
  agent/learning_engine.py    — background reflection 스레드 + lesson 업데이트 helper
  agent/reflection_engine.py  — fallback 메시지 i18n 런타임 번역 + 추정 토큰 계측
  agent/skill_library.py      — goal embedding 기반 스킬 매칭 + compile_failed 추적
  agent/episode_memory.py     — embedder 우선 저장/검색 + missing embedding background backfill
  agent/learning_metrics.py   — 일별 학습 통계/카운터/추정 토큰 summary 집계 + lift 게이팅
  agent/weekly_report.py      — 자기개선 루프 활동/신규 스킬/Python 컴파일/토큰 리포트 표시
  i18n/locales/*.po           — ko/en/ja 자기개선 루프 문자열 동기화

포함 모듈 (2026-04-06 최신):
  audio/simple_wake.py     — 정규화 전체 문구 비교로 문장 내부 부분 일치 오탐 차단
  core/VoiceCommand.py     — extend_tts_resume_guard() 추가: 세그먼트별 보호 구간 연장
  core/threads.py          — VoiceRecognitionThread 감지 후 재확인, TTSThread._collect_batch() 추가
  tts/cosyvoice_utils.py   — split_tts_segments() 추가: 자연 단위 세그먼트 분할
  tts/cosyvoice_tts.py     — _speak_segment() + split_tts_segments() 기반 멀티세그먼트 내부 처리
  ui/text_interface.py     — 스트리밍 TTS 짧은 앞문장 배치 재생 (_queue_stream_tts_sentence)
  agent/assistant_text_utils.py — LLM/AICommand 공통 목표 해석·도구 응답 정리 유틸리티 분리
  agent/planner_json_utils.py   — 잘린 JSON 응답 복구/파싱 책임 분리
  agent/automation_plan_utils.py — 브라우저/데스크톱 액션 계획 조립·정렬 유틸리티 분리
  agent/agent_planner.py        — JSON 복구 헬퍼 위임으로 플래너 본체 응집도 개선
  agent/automation_helpers.py   — resilient/adaptive 계획 조립 중복 제거

포함 모듈 (2026-04-04 최신):
  agent/execution_engine.py   — AgentOrchestrator에서 분리된 단계 실행 엔진 (ExecutionEngine)
  agent/verification_engine.py — 검증 전담 모듈 (VerificationEngine)
  agent/learning_engine.py    — 학습/기록 전담 모듈 (LearningEngine)
  agent/autonomous_executor.py — 자식 프로세스 환경변수 격리 (_build_child_env), 좀비 방지
  agent/reflection_engine.py  — 프롬프트 인젝션 방지 (_sanitize), 길이 상수화
  agent/skill_optimizer.py    — skill_id 경로 탈출 검증, 스레드 안전 초기화
  agent/safety_checker.py     — api_key 민감 키워드 추가
  core/plugin_loader.py       — 유니코드 ZIP entry 경로 검증, except 범위 축소
  core/plugin_sandbox.py      — finally 블록으로 stdout 복구 보장
  memory/memory_manager.py    — double-checked locking 싱글톤, 정규식 캐싱
  memory/trust_engine.py      — update_source_weight 스레드 락 추가
  ui/settings_llm_page.py    — SettingsDialog LLM 탭 분리 (settings_dialog.py 1190→388줄)
  ui/settings_tts_page.py    — SettingsDialog TTS 탭 분리
  ui/settings_plugin_page.py — SettingsDialog 플러그인 탭 분리

포함 모듈 (2026-04-03 최신):
  agent/goal_predictor.py   — 반복 실패 위험 예측 + orchestrator 선제 경고
  agent/learning_metrics.py — 학습 컴포넌트 lift 계측
  agent/regression_guard.py — 주간 성공률 회귀 경고
  ui/text_interface.py      — 스트리밍 청크 반영 + 문장 경계 TTS 즉시 시작
  core/resource_manager.py  — 개발 모드 `.ari_runtime` 분리 + 레거시 상태 마이그레이션
                              빌드된 exe 실행 시 런타임 루트는 `%AppData%/Ari`
  validate_repo.py          — clean environment runtime / marketplace sha256 contract smoke 추가
  market/web/src/*          — Codacy 대응용 비동기 핸들러/nullable 정리 (웹 배포 산출물과 동작 일치)
  market/supabase/functions — upload-plugin / notify-developer 검증 로직 보강 (배포 시 별도 functions deploy 필요)
  agent/agent_planner.py    — workspace audit 템플릿 강화 (창 분류/탭 추정/백업 보고)
  core/plugin_sandbox.py    — multiprocessing 기반 격리 실행 + timeout 상한 적용
  services/web_tools.py     — ddgs 우선 검색 클라이언트 + legacy fallback
  requirements.txt          — certifi / requests(>=2.33.0) / Pillow 보안 업데이트, ddgs 기본 채택

포함 모듈 (2026-03-30):
  ui/character_widget.py     — 벽/천장 타기 도중 드래그 시 중력 미적용 버그 수정
  ui/theme_editor.py         — ThemeEditorDialog 추가 (팔레트 편집 별도 창)
  ui/settings_dialog.py      — 인라인 팔레트 에디터 → ThemeEditorDialog 분리
  core/plugin_loader.py      — PluginContext 등록 훅(메뉴/명령/도구/샌드박스) + API 버전 협상 + ZIP 패키지 로드
  core/plugin_sandbox.py     — 플러그인 샌드박스 실행기 (현재는 multiprocessing 격리 방식으로 유지)
  commands/command_registry.py — register_command() 런타임 동적 등록
  commands/ai_command.py     — register_plugin_tool_handler() LLM 도구 동적 디스패치
  agent/llm_provider.py      — register_plugin_tool() 동적 스키마 확장
  ui/tray_icon.py            — add_plugin_menu_action() 트레이 메뉴 동적 삽입
  plugins/sample_plugin.py   — 메뉴·명령·도구·샌드박스 등록 예시 업데이트
  Main.py                    — PluginContext 훅 주입 (menu/command/tool/sandbox)

포함 모듈 (이전 2026-03-26):
  agent/ocr_helper.py        — easyocr/pytesseract 화면 텍스트 추출 (선택 의존성)
  agent/dag_builder.py       — 리소스 충돌 기반 의존성 DAG + 병렬 그룹 계산
  agent/embedder.py          — sentence-transformers/API/해시 임베딩 + cross-encoder 재랭킹
  agent/real_verifier.py     — 4단계 검증 파이프라인 (휴리스틱→OCR→코드→LLM)
  agent/agent_planner.py     — ActionStep DAG 필드 추가, decompose() DAG 주석
  agent/agent_orchestrator.py — 병렬 그룹 실행 + DOM 재계획 플래그 처리
  agent/strategy_memory.py   — embedding 필드 + 3단계 검색 파이프라인
  services/dom_analyser.py   — Selenium DOM 분석 + 다음 액션 제안
  services/web_tools.py      — login_and_run DOM 재계획, get_state DOM 분석 포함
  memory/trust_engine.py     — FACT 신뢰도 업데이트 엔진 (출처 가중치/충돌/decay)
  memory/user_context.py     — record_fact trust_engine 연동, optimize_memory decay 교체
  ui/theme_editor.py         — 팔레트 색상 피커 + JSON 편집 위젯
  ui/settings_dialog.py      — ThemeEditorWidget 통합, 팔레트 편집 토글
  agent/llm_provider.py      — 역할별 독립 LLM 제공자(플래너/실행) + API 키 검증 UI
  core/config_manager.py     — llm_planner_provider, llm_execution_provider, cosyvoice_dir
  tts/cosyvoice_worker.py    — cudnn.benchmark + 동적 ODE steps
  Main.py                    — 로그 자동 순환 (최대 10개 보관)

포함 모듈 (2026-03-25):
  agent/agent_orchestrator  — 병렬 실행 및 자율 반성(Reflection) 지원
  agent/agent_planner       — 플래너/실행 모델 분리, 앱 워크플로우 템플릿 확장
  agent/file_tools.py       — 확장된 파일 작업군 (이름 변경, 병합, 정리, 분석, 로그 리포트)
  agent/proactive_scheduler — 주제 기반 선제 제안 및 지정 시각 알람
  agent/real_verifier.py    — 창/URL/이미지/workflow JSON 기반 실제 상태 검증 강화
  services/web_tools.py      — 브라우저 셀렉터/액션 전략 지속 메모리 + goal_hint 재사용
  agent/automation_helpers.py — 데스크톱 창 타깃/워크플로우 기억 + wait_image
  agent/strategy_memory.py    — workflow hint 축적 및 재사용
  agent/autonomous_executor.py — adaptive/resilient workflow + planning snapshot 노출
  agent/episode_memory.py     — 목표 에피소드 기억 + recovery guidance 재주입
  core/plugin_loader.py      — 사용자 플러그인 로더 및 확장 진입점 (.py / .zip)
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
import json
from datetime import datetime

from core.settings_schema import SENSITIVE_SETTINGS_KEYS, SETTINGS_TEMPLATE_FILE

# 표준 출력 인코딩 설정 (Windows/GitHub Actions 환경 대응)
if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except AttributeError:
        pass

clean_build = "--clean" in sys.argv
one_file = "--onefile" in sys.argv
# GitHub Actions 등 CI 환경은 메모리 제한이 있어 병렬 작업 수를 절반으로 제한
_cpu = multiprocessing.cpu_count()
jobs = max(1, _cpu // 2) if os.environ.get("CI") else _cpu

print("=" * 60)
print("   Ari EXE 최적화 빌드 시스템 (Nuitka)")
print("=" * 60)
print(f"• 빌드 모드: {'단일 파일' if one_file else '폴더 독립형'}")
print(f"• 작업 유형: {'클린 빌드' if clean_build else '증분 빌드'}")
print(f"• 병렬 작업: {jobs} 코어 사용\n")
print("• 권장 사전 검증: python validate_repo.py\n")


def _ensure_safe_settings_template() -> None:
    template_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), SETTINGS_TEMPLATE_FILE)
    with open(template_path, "r", encoding="utf-8") as handle:
        payload = json.load(handle)

    leaked = [key for key in SENSITIVE_SETTINGS_KEYS if str(payload.get(key, "") or "").strip()]
    if leaked:
        raise SystemExit(
            f"설정 템플릿에 민감값이 포함되어 있습니다: {', '.join(leaked)}"
        )


_ensure_safe_settings_template()

try:
    from nuitka.__main__ import main as nuitka_main
except ImportError:
    raise SystemExit(
        "Nuitka가 설치되어 있지 않습니다. "
        "먼저 `python -m pip install nuitka`를 실행해 주세요."
    )

HERE = os.path.dirname(os.path.abspath(__file__))
DIST_DIR = os.path.join(HERE, "dist", "Ari")
PLUGIN_RUNTIME_DIR = os.path.join(HERE, "plugin_runtime")


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

if os.path.exists(PLUGIN_RUNTIME_DIR):
    print("플러그인 런타임 캐시 정리 중...")
    shutil.rmtree(PLUGIN_RUNTIME_DIR, ignore_errors=True)

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
    "--include-data-dir=i18n/locales=i18n/locales",
    "--include-data-dir=plugins=plugins",
    "--include-data-files=DNFBitBitv2.ttf=DNFBitBitv2.ttf",
    "--include-data-files=icon.png=icon.png",
    "--include-data-files=icon.ico=icon.ico",
    *(["--include-data-files=reference.wav=reference.wav"] if os.path.exists(os.path.join(HERE, "reference.wav")) else []),
    f"--include-data-files={SETTINGS_TEMPLATE_FILE}={SETTINGS_TEMPLATE_FILE}",
    "--include-data-files=tts/cosyvoice_worker.py=cosyvoice_worker.py",
    "--include-data-files=install_cosyvoice.py=install_cosyvoice.py",

    # 아이콘 설정
    *( ["--windows-icon-from-ico=icon.ico"] if os.path.exists("icon.ico") else [] ),

    # 필수 모듈 명시 (--include-package 로 자동 포함되지 않는 경우 대비)
    "--include-module=agent.confirmation_manager",
    "--include-module=agent.agent_orchestrator",
    "--include-module=agent.agent_planner",
    "--include-module=agent.agent_math",
    "--include-module=agent.assistant_text_utils",
    "--include-module=agent.autonomous_executor",
    "--include-module=agent.automation_plan_utils",
    "--include-module=agent.execution_analysis",
    "--include-module=agent.file_tools",
    "--include-module=agent.goal_predictor",
    "--include-module=agent.learning_metrics",
    "--include-module=agent.llm_provider",
    "--include-module=agent.llm_router",
    "--include-module=agent.real_verifier",
    "--include-module=agent.record_store",
    "--include-module=agent.regression_guard",
    "--include-module=agent.safety_checker",
    "--include-module=agent.tag_keywords",
    "--include-module=agent.proactive_scheduler",
    "--include-module=agent.strategy_memory",
    "--include-module=agent.episode_memory",
    "--include-module=agent.automation_helpers",
    "--include-module=agent.planner_json_utils",
    "--include-module=agent.few_shot_injector",
    "--include-module=agent.skill_library",
    "--include-module=agent.skill_optimizer",
    "--include-module=agent.reflection_engine",
    "--include-module=agent.planner_feedback",
    "--include-module=agent.weekly_report",
    "--include-module=memory.user_profile_engine",
    "--include-module=memory.memory_index",
    "--include-module=memory.memory_consolidator",
    "--include-module=commands.memory_command",
    "--include-module=core.plugin_loader",
    "--include-module=core.plugin_sandbox",
    "--include-module=core.resource_manager",
    "--include-module=services.web_tools",
    "--include-module=ui.theme",
    "--include-module=ui.theme_runtime",
    "--include-module=ui.common",
    "--include-module=ui.scheduler_panel",
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
        "anthropic",
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
        "easyocr",
        "pytesseract",
        "sentence_transformers",
        "torch",
        # 데이터 분석 / 문서 생성 / 시스템 (요청 시 설치된 경우만 포함)
        "matplotlib",
        "pandas",
        "openpyxl",
        "PIL",
        "docx",
        "bs4",
        "wmi",
        "win32api",
    ),

    # ── nofollow: C 확장 / 컴파일 불가 패키지 ──────────────────────────────────
    # Nuitka가 C로 컴파일하지 않도록 제외. 런타임에는 site-packages의
    # 사전 컴파일된 .pyd/.dll 또는 순수 Python 파일로 동작.

    # ML / 수치 연산
    "--nofollow-import-to=numpy",
    "--nofollow-import-to=torch",
    "--nofollow-import-to=torchvision",
    "--nofollow-import-to=torchaudio",
    "--nofollow-import-to=sentence_transformers",
    "--nofollow-import-to=easyocr",
    "--nofollow-import-to=cv2",
    "--nofollow-import-to=matplotlib",
    "--nofollow-import-to=tensorflow",
    "--nofollow-import-to=pandas",
    "--nofollow-import-to=sklearn",
    "--nofollow-import-to=scipy",

    # LLM / API 클라이언트 (pydantic v2 Rust 확장 포함, clcache 전처리기 실패)
    "--nofollow-import-to=groq",
    "--nofollow-import-to=openai",
    "--nofollow-import-to=anthropic",
    "--nofollow-import-to=mistralai",
    "--nofollow-import-to=httpx",
    "--nofollow-import-to=pydantic",
    "--nofollow-import-to=pydantic_core",
    "--nofollow-import-to=huggingface_hub",

    # 기타
    "--nofollow-import-to=pytest",
    "--nofollow-import-to=IPython",
    "--nofollow-import-to=PIL",
    "--nofollow-import-to=pygments",
    "--nofollow-import-to=reportlab",
    "--nofollow-import-to=lxml",
    "--nofollow-import-to=mouseinfo",
    "--nofollow-import-to=comtypes.test",
    "--nofollow-import-to=wmi",
    "--nofollow-import-to=win32api",
    "--nofollow-import-to=win32con",
    "--nofollow-import-to=win32com",
    "--nofollow-import-to=openpyxl",
    
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
        if os.path.exists(DIST_DIR):
            shutil.rmtree(DIST_DIR)
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
