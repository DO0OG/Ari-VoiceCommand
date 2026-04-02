"""
에이전트 플래너 (Agent Planner)
복잡한 목표를 실행 가능한 단계들로 분해하고,
실패한 단계를 LLM이 자동으로 수정합니다.
과거 전략 기억을 참고하여 더 나은 계획을 수립합니다.
"""
import json
import logging
import os
import re
import time
from datetime import datetime
from dataclasses import dataclass, field
from typing import List, Optional, Dict

from agent.execution_analysis import is_read_only_step_content

# JSON 파싱 정규식 — 모듈 로드 시 1회 컴파일
_RE_CODE_FENCE = re.compile(r'```(?:json)?\s*', re.IGNORECASE)
_RE_JSON_ARRAY  = re.compile(r'\[.*\]', re.DOTALL)
_RE_JSON_OBJECT = re.compile(r'\{.*\}', re.DOTALL)

_SITE_ALIASES = {
    "네이버": "https://www.naver.com",
    "naver": "https://www.naver.com",
    "구글": "https://www.google.com",
    "google": "https://www.google.com",
    "유튜브": "https://www.youtube.com",
    "youtube": "https://www.youtube.com",
    "깃허브": "https://github.com",
    "github": "https://github.com",
    "지메일": "https://mail.google.com",
    "gmail": "https://mail.google.com",
}

_SPECIAL_FOLDER_ALIASES = {
    "바탕화면": "Desktop",
    "desktop": "Desktop",
    "다운로드": "Downloads",
    "download": "Downloads",
    "downloads": "Downloads",
    "문서": "Documents",
    "documents": "Documents",
    "사진": "Pictures",
    "pictures": "Pictures",
    "이미지": "Pictures",
    "동영상": "Videos",
    "videos": "Videos",
    "음악": "Music",
    "music": "Music",
}

_DEV_SCOPE_RE = re.compile(
    r"(voicecommand(?:/(?:agent|core|ui|plugins|tests)\b|\s*(?:저장소|repository|codebase|repo)\b)?|voicecommand/validate_repo\.py\b|\bdocs\b)",
    re.IGNORECASE,
)
_DEV_PRODUCT_RE = re.compile(r"\bvoicecommand\b", re.IGNORECASE)
_DEV_ACTION_RE = re.compile(
    r"(validate_repo\.py|--compile-only|pytest|unittest|회귀|리팩토링|코드\s*(?:변경|수정)|테스트(?:\s*실행)?|문서\s*수정|bug|fix|refactor|구현|검증|개선(?:\s*과제)?|분석|전체\s*파악|영향받는\s*테스트)",
    re.IGNORECASE,
)
_DEV_REPO_RE = re.compile(r"(저장소|repository|codebase|\brepo\b|프로젝트)", re.IGNORECASE)
_LLM_RETRYABLE_ERROR_RE = re.compile(
    r"(429|resource_exhausted|quota exceeded|rate limit|retry in|retrydelay|temporar|timeout|overloaded|too many requests)",
    re.IGNORECASE,
)
_LLM_RETRY_DELAY_RE_LIST = (
    re.compile(r"retry in\s*([\d.]+)\s*s", re.IGNORECASE),
    re.compile(r"retrydelay['\"]?\s*[:=]\s*['\"]?([\d.]+)\s*s", re.IGNORECASE),
    re.compile(r"'retryDelay':\s*'([\d.]+)s'", re.IGNORECASE),
)
_DISALLOWED_DEVELOPER_PATTERNS = (
    (re.compile(r"step_outputs\s*\[\s*\d+\s*\]"), "numeric step_outputs access"),
    (re.compile(r"os\.environ\s*\[\s*['\"]repo_root['\"]\s*\]"), "repo_root env access"),
    (re.compile(r"\$env:repo_root", re.IGNORECASE), "repo_root env access"),
    (re.compile(r"__file__"), "__file__ path inference"),
    (re.compile(r"os\.path\.expanduser\(\s*['\"]~['\"]\s*\)"), "home path inference"),
    (re.compile(r"desktop_path"), "desktop path use in developer task"),
    (re.compile(r"[A-Za-z]:\\\\"), "hardcoded absolute path"),
)
_DEVELOPER_PATH_LITERAL_RE = re.compile(
    r"(?<![A-Za-z0-9_])((?:VoiceCommand|docs|tests|market|supabase|\.github|\.claude|\.idea)[/\\][A-Za-z0-9_./\\-]+)",
    re.IGNORECASE,
)
_DEVELOPER_RESCAN_PATTERNS = (
    re.compile(r"repo_structure\.txt", re.IGNORECASE),
    re.compile(r"collected\.json", re.IGNORECASE),
    re.compile(r"Get-ChildItem\s+-Recurse\s+-Directory", re.IGNORECASE),
    re.compile(r"\brglob\s*\(\s*['\"]\*\.py['\"]\s*\)", re.IGNORECASE),
    re.compile(r"\bPath\s*\(\s*repo_root\s*\)\.rglob\s*\(", re.IGNORECASE),
    re.compile(r"\bos\.walk\s*\(\s*repo_root", re.IGNORECASE),
    re.compile(r"\bSelect-Object\s+FullName\b", re.IGNORECASE),
    re.compile(r"\bOut-File\b", re.IGNORECASE),
)
_DEFAULT_DEVELOPER_SCOPE_PREFIXES = (
    "voicecommand/agent",
    "voicecommand/core",
    "voicecommand/ui",
    "voicecommand/plugins",
    "voicecommand/tests",
    "docs",
    "voicecommand/validate_repo.py",
)


@dataclass
class ActionStep:
    step_id: int
    step_type: str        # "python" | "shell" | "think"
    content: str          # 실행할 코드 또는 명령 (think는 빈 문자열 가능)
    description_kr: str
    expected_output: str = ""
    condition: str = ""        # Python 표현식. 비어있으면 항상 실행.
    on_failure: str = "abort"  # "abort"(중단) | "skip"(건너뜀) | "continue"(계속)
    depends_on: List[int] = field(default_factory=list)
    writes: List[str] = field(default_factory=list)
    reads: List[str] = field(default_factory=list)
    parallel_group: int = -1


@dataclass
class GoalProfile:
    normalized_goal: str
    wants_save: bool = False
    wants_summary: bool = False
    wants_search: bool = False
    wants_news: bool = False
    wants_desktop: bool = False
    wants_folder: bool = False
    wants_file: bool = False
    wants_system_info: bool = False
    wants_copy: bool = False
    wants_move: bool = False
    wants_list: bool = False
    wants_delete: bool = False
    wants_open: bool = False
    wants_login: bool = False
    wants_browser: bool = False
    wants_download: bool = False
    wants_rename: bool = False
    wants_merge: bool = False
    wants_organize: bool = False
    wants_analyze: bool = False
    wants_log_report: bool = False
    wants_security_audit: bool = False
    wants_type_text: bool = False
    wants_window_summary: bool = False
    wants_link_collection: bool = False
    wants_batch_rename: bool = False
    wants_file_set_scan: bool = False
    source_path: str = ""
    destination_path: str = ""
    url: str = ""
    target_name: str = "result"
    preferred_format: str = "auto"
    rename_target: str = ""
    all_paths: List[str] = field(default_factory=list)
    input_text: str = ""


_SYS_JSON_ONLY = "당신은 JSON만 반환하는 전문가입니다. 설명 없이 순수 JSON만 반환하세요."

_DECOMPOSE_PROMPT = """\
다음 목표를 달성하기 위한 실행 단계를 JSON 배열로 반환하세요.

목표: {goal}
{context_block}
규칙:
- step_type: "python" (파이썬 코드), "shell" (CMD), "think" (判断/分析, content 없음)
- 단순한 작업은 1단계로 충분합니다
- 코드는 즉시 실행 가능하게 작성하세요
- 파이썬 코드는 여러 문장이어도 됩니다. `with`, `for`, `if`, `try` 같은 복합문은 세미콜론으로 이어붙이지 말고 줄바꿈으로 작성하세요.
- 이전 단계 출력은 파이썬에서 step_outputs 딕셔너리로 접근 가능합니다 (키: "step_0_output", "step_1_output", ...)
- 이전 단계 결과에 의존하는 단계는 반드시 condition을 설정하세요 (예: 폴더 생성 후 파일 저장)
- condition: 실행 조건 표현식 (예: "len(step_outputs.get('step_0_output','')) > 0 and '오류' not in step_outputs.get('step_0_output','')"), 생략 시 항상 실행
- on_failure: "abort"(중단), "skip"(건너뜀), "continue"(계속) 중 하나
- Windows 바탕화면 경로: 파이썬 코드 실행 시 'desktop_path' 변수를 즉시 사용할 수 있습니다. os.path.join(desktop_path, '폴더명') 식으로 사용하세요.
- 파일 저장 시 반드시 폴더가 존재하는지 확인 후 생성: os.makedirs(path, exist_ok=True)
- 웹 정보가 필요하면 requests+임의 API 키를 쓰지 말고, 이미 제공된 `web_search(query, max_results=5)` 와 `web_fetch(url)`를 우선 사용하세요.
- 문서를 저장할 때는 `save_document(directory, base_name, content, preferred_format='auto', title='')` 도우미를 사용할 수 있습니다.
- `preferred_format='auto'`면 내용 구조에 따라 txt/md/pdf 중 적절한 형식을 자동 선택합니다.
- 파일 작업에는 `rename_file`, `merge_files`, `organize_folder`, `analyze_data`, `generate_report`, `detect_file_set`, `batch_rename_files` 도우미를 사용할 수 있습니다.
- GUI/브라우저 자동화에는 `open_url`, `open_path`, `launch_app`, `wait_seconds`, `click_screen`, `click_image`, `is_image_visible`, `move_mouse`, `type_text`, `press_keys`, `hotkey`, `take_screenshot`, `read_clipboard`, `write_clipboard`, `wait_for_window`, `get_active_window_title`, `list_open_windows`, `get_desktop_state`, `browser_login`, `run_browser_actions`, `run_adaptive_browser_workflow`, `run_resilient_browser_workflow`, `run_desktop_workflow`, `run_adaptive_desktop_workflow`, `run_resilient_desktop_workflow`, `get_runtime_state`, `get_state_transition_history`, `get_learned_strategies`, `get_planning_snapshot`, `get_recovery_candidates`, `get_recovery_guidance`, `get_recent_goal_episodes` 헬퍼를 사용할 수 있습니다.
- 브라우저 액션 타입으로 `wait_url`, `wait_title`, `wait_selector`, `read_title`, `read_url`, `read_links`, `download_wait`를 사용할 수 있습니다.
- 반복 GUI/브라우저 작업 전에는 `get_planning_snapshot_summary(goal_hint='...')` 또는 `get_planning_snapshot(goal_hint='...')`로 현재 상태 + 과거 성공 전략을 먼저 읽고, 가능한 경우 `run_resilient_browser_workflow(...)` / `run_resilient_desktop_workflow(...)`를 우선 사용하세요.
- context에 `recent_goal_episodes`, `execution_policy_summary`, `recovery_candidates_json`, `recovery_guidance`가 있으면 우선 참고해 같은 실패를 반복하지 마세요.
- `run_browser_actions(url, actions, goal_hint='로그인 후 다운로드')`처럼 `goal_hint`를 함께 주면 이전 성공 액션 시퀀스를 재사용할 수 있습니다.
- `run_desktop_workflow(goal_hint='메모장에 메모 저장', app_target='notepad', expected_window='메모장', actions=[...])`처럼 사용하면 창 전략과 후속 액션을 함께 재사용할 수 있습니다.
- 기존 문서를 덮어쓸 가능성이 있으면 `get_backup_history()` / `restore_last_backup(path)`를 사용해 복구 경로를 고려하세요.
- `YOUR_API_KEY`, `newsapi.org`, `nltk.download`, 외부 유료 API 의존 코드는 금지합니다.
- 한국 뉴스 요약은 검색 결과 텍스트를 적절히 잘라 저장하면 충분합니다. 복잡한 NLP 라이브러리를 추가하지 마세요.
- 반드시 JSON 배열만 반환하세요

출력 형식:
[
  {{
    "step_type": "python",
    "content": "실행할 코드",
    "description_kr": "단계 설명",
    "expected_output": "예상 결과",
    "condition": "",
    "on_failure": "abort"
  }}
]"""

_DEVELOPER_DECOMPOSE_PROMPT = """\
다음 저장소 개발 목표를 달성하기 위한 실행 단계를 JSON 배열로 반환하세요.

목표: {goal}
{context_block}
규칙:
- step_type은 "python", "shell", "think" 중 하나만 사용하세요.
- 최대 4단계만 반환하세요.
- shell 단계는 PowerShell 명령으로 작성하세요.
- shell 명령은 저장소 루트(repo_root)를 현재 작업 디렉터리로 사용한다고 가정하세요.
- python 단계에서는 `repo_root`(저장소 루트)와 `module_dir`(VoiceCommand 패키지 루트)를 바로 사용할 수 있습니다.
- content는 짧고 실행 가능해야 하며, 파일 내용 전체를 길게 복붙하지 마세요.
- 이전 단계 출력은 파이썬에서 step_outputs 딕셔너리로 접근 가능합니다.
- 저장소 스캔 결과(step_0_output, step_1_output 등)가 아직 없으면 첫 계획은 정보 수집 중심으로만 작성하세요.
- 저장소 스캔 결과가 이미 있으면 그 결과를 바탕으로 개선 과제 1개를 고르고, 한 파일 또는 한 책임 단위씩만 수정하세요.
- 수정/읽기 대상은 `VoiceCommand/agent`, `VoiceCommand/core`, `VoiceCommand/ui`, `VoiceCommand/plugins`, `VoiceCommand/tests`, `docs`, `VoiceCommand/validate_repo.py` 범위로 제한하세요.
- 경로를 하드코딩하지 말고 `repo_root`와 `module_dir`를 기준으로 계산하거나 먼저 탐색하세요.
- 저장소 스캔이 끝난 뒤에는 다시 전체 스캔(`repo_structure.txt`, `collected.json`, `repo_root.rglob('*.py')`)으로 돌아가지 마세요.
- 검증 단계에는 반드시 `py -3.11 VoiceCommand\\validate_repo.py --compile-only` 또는 `py -3.11 VoiceCommand\\validate_repo.py` 와 영향받는 `VoiceCommand.tests...` / `VoiceCommand/tests/...` 테스트 실행을 포함하세요.
- `py_compile`, `tests/` 루트 경로, `&&` 체인은 금지합니다.
- 반드시 JSON 배열만 반환하세요.

출력 형식:
[
  {{
    "step_type": "shell",
    "content": "실행할 PowerShell 명령",
    "description_kr": "단계 설명",
    "expected_output": "예상 결과",
    "condition": "",
    "on_failure": "abort"
  }}
]
"""

_DEVELOPER_RETRY_PROMPT = """\
저장소 스캔이 끝났습니다. 이제 실제 코드를 수정하는 2단계 계획을 JSON 배열로 반환하세요.

목표: {goal}
{context_block}
규칙:
- 저장소 스캔/목록 조회 단계는 절대 포함하지 마세요. 이미 완료됐습니다.
- 정확히 2단계만 반환하세요: [코드_수정, 검증].
- 코드_수정 단계: 위 컨텍스트에서 파악한 실제 파일 하나를 선택해 `open(path, 'w')`나 `path.write_text()`로 내용을 수정하세요.
  반드시 실제 Python/shell 코드를 작성하세요. `print('edit one file')` 같은 자리표시자는 절대 금지입니다.
- 수정 대상은 `VoiceCommand/agent`, `VoiceCommand/core`, `VoiceCommand/ui`, `VoiceCommand/plugins`, `VoiceCommand/tests`, `docs` 범위 안에서만 고르세요.
- 검증 단계에는 반드시 `py -3.11 VoiceCommand\\validate_repo.py --compile-only` 와 영향받는 테스트 실행을 포함하세요.
- `py_compile`, `tests/` 루트 경로, `&&`, 전체 저장소 재스캔은 금지합니다.
- step_type은 "python" 또는 "shell"만 사용하세요.
- python 단계에서는 `repo_root`, `module_dir`, `step_outputs`를 바로 사용할 수 있습니다.
- content는 실제 실행 가능한 코드여야 하며, 반드시 6줄 이하로 작성하세요 (1000 token 제한).
- 반드시 JSON 배열만 반환하세요.

나쁜 예(금지):
[{{"step_type":"python","content":"print('edit one file')","description_kr":"파일 편집"}}]

좋은 예:
[
  {{"step_type":"python","content":"import os\\npath = os.path.join(repo_root,'VoiceCommand','agent','skill_library.py')\\ntext = open(path,'r',encoding='utf-8').read()\\ntext = text.replace('old_pattern','new_pattern',1)\\nopen(path,'w',encoding='utf-8').write(text)\\nprint('done')", "description_kr":"skill_library.py 패턴 수정","expected_output":"done"}},
  {{"step_type":"shell","content":"py -3.11 VoiceCommand\\\\validate_repo.py --compile-only; py -3.11 -m unittest VoiceCommand.tests.test_skill_library","description_kr":"저장소 검증과 영향 테스트","expected_output":"compile-only checks passed"}}
]
"""

_FIX_PROMPT = """\
다음 코드/명령이 오류로 실패했습니다. 수정된 버전을 JSON으로 반환하세요.

원래 코드:
{content}

오류 메시지:
{error}

목표: {goal}
{context_block}
수정 시 주의:
- 오류 원인을 분석하고 근본적으로 수정하세요
- 동일한 방식으로 재시도하지 마세요
- Windows 바탕화면 경로: 파이썬 코드 실행 시 'desktop_path' 변수를 즉시 사용할 수 있습니다. os.path.join(desktop_path, '폴더명') 식으로 사용하세요.
- 저장소/코드 작업에서는 `repo_root`와 `module_dir`를 우선 사용하고, Desktop 경로를 추측하지 마세요.
- 경로나 실행 파일 위치를 하드코딩하지 말고, 런타임 탐색 또는 제공된 헬퍼를 사용하세요.
- 웹 검색이 필요하면 `web_search` / `web_fetch`를 사용하고, `YOUR_API_KEY` 같은 자리표시자는 절대 사용하지 마세요.
- 문서 저장은 가능하면 `save_document(...)` 도우미를 사용하세요.
- 파일 작업은 가능하면 `rename_file`, `merge_files`, `organize_folder`, `analyze_data`, `generate_report`, `detect_file_set`, `batch_rename_files` 도우미를 사용하세요.
- GUI/브라우저 자동화가 필요하면 가능한 한 내장 헬퍼(`open_url`, `launch_app`, `click_screen`, `type_text`, `wait_for_window`, `list_open_windows`, `get_desktop_state`, `browser_login`, `run_browser_actions`, `run_adaptive_browser_workflow`, `run_resilient_browser_workflow`, `run_desktop_workflow`, `run_adaptive_desktop_workflow`, `run_resilient_desktop_workflow`, `get_runtime_state`, `get_state_transition_history`, `get_learned_strategies`, `get_planning_snapshot`, `get_recovery_candidates`, `get_recovery_guidance`, `get_recent_goal_episodes` 등)를 사용하세요.
- 브라우저에서 리다이렉트/동적 로딩이 예상되면 `wait_url`, `wait_title`, `wait_selector` 같은 액션을 포함하세요.
- 이미 비슷한 전략이 있다면 `get_planning_snapshot_summary(goal_hint=...)`를 우선 참고하고, 필요할 때만 전체 `get_planning_snapshot(...)` 또는 `get_learned_strategies(...)`를 읽으세요.
- 브라우저 작업은 가능하면 `goal_hint`를 명시해 재사용 가능한 액션 전략을 남기세요.
- 기존 파일을 덮어썼다면 `get_backup_history()`를 확인하고 필요 시 `restore_last_backup(path)`로 복구하도록 수정하세요.
- `with`, `for`, `if`, `try` 같은 복합문은 세미콜론 한 줄 코드로 만들지 마세요. 여러 줄로 작성하세요.
- 반드시 JSON 객체만 반환하세요

출력 형식:
{{
  "step_type": "python",
  "content": "수정된 코드",
  "description_kr": "수정 이유",
  "expected_output": "예상 결과"
}}"""

_VERIFY_PROMPT = """\
다음 실행 결과가 목표를 달성했는지 평가하세요.

목표: {goal}

실행 결과:
{results_summary}

평가 기준:
- 파일/폴더 생성 등 시스템 상태 변화는 코드 출력에 오류가 없을 때만 achieved=true
- 단계 출력에 오류 메시지, 예외, "실패" 등이 포함되면 achieved=false
- 불확실하면 achieved=false

반드시 JSON 객체만 반환하세요:
{{
  "achieved": true,
  "summary_kr": "달성 여부 한국어 요약 (1~2문장)"
}}"""

_REFLECT_PROMPT = """\
에이전트가 목표 달성에 최종적으로 실패했습니다. 실패 원인을 분석하고 다음 시도를 위한 '교훈'을 JSON으로 작성하세요.

목표: {goal}

실행 이력 요약:
{history_summary}

작성 규칙:
- 실패의 근본 원인을 기술하세요 (예: 라이브러리 부재, 권한 문제, 논리 오류 등)
- 다음 시도에서 반드시 피해야 할 접근법을 명시하세요
- 권장되는 대안 접근법을 한 문장으로 정리하세요
- 반드시 JSON 객체만 반환하세요

출력 형식:
{{
  "reason": "실패 원인",
  "avoid": "피해야 할 점",
  "lesson": "다음 시도를 위한 핵심 교훈"
}}"""


class AgentPlanner:
    """목표 분해 / 단계 수정 / 결과 검증 플래너"""

    def __init__(self, llm_provider):
        self.llm = llm_provider

    def reflect(self, goal: str, history_summary: str) -> Dict[str, str]:
        """실패 원인 분석 및 교훈 도출 (planner_model 사용)"""
        prompt = _REFLECT_PROMPT.format(goal=goal, history_summary=history_summary)
        try:
            resp = self._call_llm(prompt, model=self.llm.planner_model,
                                  client_override=self.llm.planner_client,
                                  provider_override=self.llm.planner_provider,
                                  role_hint="planner")
            return self._parse_object(resp) or {}
        except Exception as e:
            logging.error(f"[Planner] 반성 실패: {e}")
            return {}

    # ── 공개 API ──────────────────────────────────────────────────────────────

    def decompose(self, goal: str, context: Dict[str, str] = None) -> List[ActionStep]:
        """목표를 실행 단계 목록으로 분해 (planner_model 사용)"""
        from agent.dag_builder import extract_resources, build_dag, assign_parallel_groups, annotate_steps
        from agent.few_shot_injector import get_few_shot_injector
        from agent.planner_feedback import get_planner_feedback_loop

        def _annotate(steps: List[ActionStep]) -> List[ActionStep]:
            for step in steps:
                step.reads, step.writes = extract_resources(step.content, step.step_type)
            dag = build_dag(steps)
            groups = assign_parallel_groups(dag)
            return annotate_steps(steps, dag, groups)

        templated = self._build_template_plan(goal)
        if templated:
            logging.info(f"[Planner] 템플릿 계획 사용: {goal}")
            return _annotate(templated)

        is_dev_goal = self.is_developer_goal(goal)

        # 과거 전략 기억 주입
        if is_dev_goal:
            ctx_block = self._fmt_developer_context(context)
            failure_hints = self._get_failure_hints(goal)
            if failure_hints:
                ctx_block = "## 최근 실패 힌트\n" + failure_hints + "\n" + ctx_block
        else:
            strategy_ctx = self._get_strategy_context(goal)
            ctx_block = self._fmt_context(context)
            if strategy_ctx:
                ctx_block = strategy_ctx + "\n" + ctx_block
            few_shot = get_few_shot_injector().get_examples(goal)
            if few_shot:
                ctx_block = few_shot + "\n" + ctx_block
            feedback_hints = get_planner_feedback_loop().get_hints(goal, [])
            if feedback_hints:
                ctx_block = feedback_hints + "\n" + ctx_block

        prompt_template = _DEVELOPER_DECOMPOSE_PROMPT if is_dev_goal else _DECOMPOSE_PROMPT
        prompt = prompt_template.format(goal=goal, context_block=ctx_block)
        raw = self._call_llm(prompt, model=self.llm.planner_model,
                             client_override=self.llm.planner_client,
                             provider_override=self.llm.planner_provider,
                             role_hint="planner")
        self._write_trace("decompose", goal, raw)
        items = self._parse_array(raw)
        if items and is_dev_goal:
            items = self._sanitize_developer_items(items, goal=goal, context=context)
        if not items:
            if is_dev_goal:
                retry_items = self._retry_developer_decompose(goal, context, ctx_block)
                if retry_items:
                    items = retry_items
            if not items and is_dev_goal:
                fallback_steps = self._build_developer_bootstrap_plan(context)
                if fallback_steps:
                    logging.info("[Planner] 개발 목표용 부트스트랩 계획 사용")
                    return _annotate(fallback_steps)
        if not items:
            logging.warning(f"[Planner] decompose 파싱 실패: {raw[:200]}")
            return []
        steps = [
            ActionStep(
                step_id=i,
                step_type=s.get("step_type", "python"),
                content=s.get("content", ""),
                description_kr=s.get("description_kr", f"단계 {i+1}"),
                expected_output=s.get("expected_output", ""),
                condition=s.get("condition", ""),
                on_failure=s.get("on_failure", "abort"),
            )
            for i, s in enumerate(items)
        ]
        return _annotate(steps)

    def is_developer_goal(self, goal: str) -> bool:
        normalized = re.sub(r"\s+", " ", (goal or "").strip())
        if not normalized:
            return False
        has_product = bool(_DEV_PRODUCT_RE.search(normalized))
        has_repo_scope = bool(_DEV_SCOPE_RE.search(normalized)) or bool(_DEV_REPO_RE.search(normalized)) or has_product
        has_dev_action = bool(_DEV_ACTION_RE.search(normalized))
        return has_repo_scope and has_dev_action

    def _retry_developer_decompose(self, goal: str, context: Dict[str, str], ctx_block: str) -> list:
        if not context or not any(key.startswith("step_") for key in context):
            return []
        # 재시도 시 컨텍스트를 최소화 — 실패 힌트/긴 로그 제외하고 순수 개발 컨텍스트만 사용
        retry_ctx = self._fmt_developer_context(context)
        retry_prompt = _DEVELOPER_RETRY_PROMPT.format(goal=goal, context_block=retry_ctx)
        retry_raw = self._call_llm(
            retry_prompt,
            model=self.llm.planner_model,
            client_override=self.llm.planner_client,
            provider_override=self.llm.planner_provider,
            role_hint="planner",
        )
        self._write_trace("decompose_retry", goal, retry_raw)
        retry_items = self._parse_array(retry_raw)
        if retry_items:
            retry_items = self._sanitize_developer_items(retry_items, goal=goal, context=context)
        if retry_items:
            logging.info("[Planner] 개발 목표 후속 계획 재요청 성공")
            return retry_items
        logging.warning("[Planner] decompose_retry 실패 → 최소 변경 fallback 없이 계획 실패 처리")
        return []

    def _build_developer_bootstrap_plan(self, context: Dict[str, str] = None) -> List[ActionStep]:
        context = context or {}
        if any(key.startswith("step_") for key in context):
            return []
        return [
            ActionStep(
                step_id=0,
                step_type="python",
                content=(
                    "import json\n"
                    "import os\n"
                    "targets = {\n"
                    "    'agent': os.path.join(module_dir, 'agent'),\n"
                    "    'core': os.path.join(module_dir, 'core'),\n"
                    "    'ui': os.path.join(module_dir, 'ui'),\n"
                    "    'plugins': os.path.join(module_dir, 'plugins'),\n"
                    "    'tests': os.path.join(module_dir, 'tests'),\n"
                    "    'docs': os.path.join(repo_root, 'docs'),\n"
                    "}\n"
                    "summary = {}\n"
                    "for label, target_path in targets.items():\n"
                    "    if not os.path.isdir(target_path):\n"
                    "        continue\n"
                    "    files = []\n"
                    "    for root, _, names in os.walk(target_path):\n"
                    "        for name in sorted(names):\n"
                    "            rel = os.path.relpath(os.path.join(root, name), target_path).replace('\\\\', '/')\n"
                    "            files.append(rel)\n"
                    "    summary[label] = {'file_count': len(files), 'samples': files[:15]}\n"
                    "print(json.dumps(summary, ensure_ascii=False))"
                ),
                description_kr="저장소 구조 스캔",
                expected_output="target directory summary json",
                on_failure="abort",
            ),
            ActionStep(
                step_id=1,
                step_type="python",
                content=(
                    "import os\n"
                    "matches = []\n"
                    "for search_root in (module_dir, repo_root):\n"
                    "    for root, _, names in os.walk(search_root):\n"
                    "        if 'validate_repo.py' in names:\n"
                    "            matches.append(os.path.join(root, 'validate_repo.py'))\n"
                    "if not matches:\n"
                    "    raise FileNotFoundError('validate_repo.py not found under repo_root')\n"
                    "target_path = sorted(set(matches))[0]\n"
                    "# 경로만 출력 — 소스 전체를 읽으면 컨텍스트가 폭발하므로 금지\n"
                    "print(f'validate_repo_path={target_path}')"
                ),
                description_kr="검증 스크립트 확인",
                expected_output="validate_repo_path=<path>",
                on_failure="abort",
            ),
            ActionStep(
                step_id=2,
                step_type="python",
                content=(
                    "import json\n"
                    "import os\n"
                    "tests_dir = os.path.join(module_dir, 'tests')\n"
                    "if not os.path.isdir(tests_dir):\n"
                    "    raise FileNotFoundError('tests directory not found under module_dir')\n"
                    "names = [\n"
                    "    name\n"
                    "    for name in sorted(os.listdir(tests_dir))\n"
                    "    if os.path.isfile(os.path.join(tests_dir, name))\n"
                    "]\n"
                    "print(json.dumps(names, ensure_ascii=False))"
                ),
                description_kr="관련 테스트 목록 수집",
                expected_output="test file list",
                on_failure="abort",
            ),
        ]

    def _build_template_plan(self, goal: str) -> List[ActionStep]:
        """LLM이 자주 실패하는 검색-요약-저장 계열 작업은 안정적인 템플릿으로 우선 처리."""
        if self.is_developer_goal(goal):
            return []

        profile = self._profile_goal(goal)

        if profile.wants_system_info or profile.wants_security_audit:
            return self._build_system_info_plan(profile)

        if profile.wants_browser and profile.url and profile.wants_login and profile.wants_link_collection:
            return self._build_browser_login_and_collect_plan(profile)

        if profile.wants_browser and profile.url and profile.wants_login:
            return self._build_browser_login_prep_plan(profile)

        if profile.wants_browser and profile.url and profile.input_text and profile.wants_save:
            return self._build_browser_input_save_plan(profile)

        if profile.wants_browser and profile.url and profile.input_text:
            return self._build_browser_input_plan(profile)

        if profile.wants_browser and profile.url and profile.wants_link_collection and profile.wants_save:
            return self._build_browser_link_collection_save_plan(profile)

        if profile.wants_browser and profile.url and profile.wants_link_collection:
            return self._build_browser_link_collection_plan(profile)

        if profile.wants_browser and profile.url and profile.wants_download:
            return self._build_browser_download_plan(profile)

        if profile.wants_open and profile.target_name in {"notepad", "explorer", "chrome", "msedge", "code", "calculator"}:
            return self._build_desktop_app_plan(profile)

        if profile.wants_open and (profile.url or profile.source_path or profile.target_name not in {"result", "summary"}):
            return self._build_open_target_plan(profile)

        if profile.wants_rename and profile.source_path and profile.rename_target:
            return self._build_rename_plan(profile)

        if profile.wants_batch_rename and (profile.source_path or profile.wants_desktop):
            return self._build_batch_rename_plan(profile)

        if profile.wants_file_set_scan and (profile.source_path or profile.wants_desktop):
            return self._build_file_set_scan_plan(profile)

        if profile.wants_merge and len(profile.all_paths) >= 2:
            return self._build_merge_files_plan(profile)

        if profile.wants_log_report and profile.source_path:
            return self._build_log_report_plan(profile)

        if profile.wants_window_summary and (profile.wants_desktop or profile.wants_folder):
            return self._build_window_summary_save_plan(profile)

        if profile.wants_organize and (profile.source_path or profile.wants_desktop):
            return self._build_organize_folder_plan(profile)

        if profile.wants_analyze and profile.source_path:
            return self._build_data_analysis_plan(profile)

        if profile.wants_list and (profile.source_path or profile.wants_desktop) and profile.wants_save:
            return self._build_directory_listing_plan(profile)

        if profile.wants_copy and profile.source_path and profile.destination_path:
            return self._build_copy_move_plan(profile, move=False)

        if profile.wants_move and profile.source_path and profile.destination_path:
            return self._build_copy_move_plan(profile, move=True)

        if profile.wants_folder and any(token in profile.normalized_goal for token in ("만들", "생성")):
            return self._build_create_folder_plan(profile)

        if profile.source_path and profile.wants_summary and profile.wants_save:
            return self._build_file_summary_plan(profile)

        if profile.wants_search and profile.wants_save:
            return self._build_search_save_plan(profile)

        return []

    def _profile_goal(self, goal: str) -> GoalProfile:
        normalized = re.sub(r"\s+", " ", goal.strip())
        lower = normalized.lower()
        source_path = ""
        destination_path = ""
        url_match = re.search(r'(https?://[^\s]+)', goal)
        url = url_match.group(1) if url_match else ""
        if not url:
            for alias, mapped_url in _SITE_ALIASES.items():
                if alias in normalized:
                    url = mapped_url
                    break
        windows_path_pattern = r'([A-Za-z]:\\(?:[^\\/:*?"<>|\r\n]+\\)*[^\\/:*?"<>|\r\n]+(?:\.[A-Za-z0-9]+)?)'
        dir_path_pattern = r'([A-Za-z]:\\(?:[^\\/:*?"<>|\r\n]+\\)*[^\\/:*?"<>|\r\n]+)(?=\s*(?:폴더|디렉토리|목록|리스트|저장|보여|나열|$))'
        path_match = re.search(windows_path_pattern, goal) or re.search(dir_path_pattern, goal)
        path_tail_pattern = r'\s+(?:로|에|를|으로|후|하고|목록|리스트|저장|보여줘|나열|파일|폴더|디렉토리|요약|정리|복사|이동|분석|리포트|보고|csv|json|txt|md|pdf|log|CSV|JSON|TXT|MD|PDF|LOG|rename|to)\b'
        if path_match:
            source_path = re.split(path_tail_pattern, path_match.group(1), maxsplit=1)[0].strip()
            source_path = re.sub(r'\s*(폴더|디렉토리)$', '', source_path).strip()
        all_paths = re.findall(windows_path_pattern, goal)
        if len(all_paths) < 2:
            dir_paths = re.findall(dir_path_pattern, goal)
            for p in dir_paths:
                if p not in all_paths:
                    all_paths.append(p)
        cleaned_paths = []
        for path in all_paths:
            cleaned = re.split(path_tail_pattern, path, maxsplit=1)[0].strip()
            cleaned_paths.append(cleaned)
        all_paths = cleaned_paths
        if len(all_paths) >= 2:
            source_path = all_paths[0]
            destination_path = all_paths[1]
        if not source_path:
            source_path = self._infer_special_folder_path(normalized, lower)
        preferred_format = "auto"
        for fmt in ("pdf", "md", "txt"):
            if fmt in lower:
                preferred_format = fmt
                break

        target_name = "result"
        folder_name = self._extract_folder_name(normalized)
        folder_name_match = re.search(r'([가-힣A-Za-z0-9._-]+)\s*폴더', normalized)
        if folder_name:
            target_name = folder_name
        elif "뉴스" in normalized:
            target_name = "news"
        elif "요약" in normalized:
            target_name = "summary"
        elif "보고" in normalized or "리포트" in normalized:
            target_name = "report"
        elif folder_name_match:
            target_name = folder_name_match.group(1)
        elif any(token in normalized for token in ("메모장", "notepad")):
            target_name = "notepad"
        elif any(token in normalized for token in ("크롬", "chrome")):
            target_name = "chrome"
        elif any(token in normalized for token in ("엣지", "edge")):
            target_name = "msedge"
        elif any(token in lower for token in ("vscode", "vs code", "visual studio code")) or any(token in normalized for token in ("코드", "코드 에디터")):
            target_name = "code"
        elif any(token in normalized for token in ("계산기",)) or any(token in lower for token in ("calculator", "calc")):
            target_name = "calculator"
        elif "탐색기" in normalized or "explorer" in lower:
            target_name = "explorer"

        rename_target = self._extract_rename_target(normalized, all_paths[0] if all_paths else source_path)
        input_text = self._extract_input_text(goal, all_paths, url)

        return GoalProfile(
            normalized_goal=normalized,
            wants_save=any(token in normalized for token in ("저장", "파일", "문서", "내보내기")),
            wants_summary=any(token in normalized for token in ("요약", "정리", "보고", "리포트")),
            wants_search=any(token in normalized for token in ("검색", "찾아", "조사", "뉴스", "웹", "인터넷")),
            wants_news="뉴스" in normalized,
            wants_desktop="바탕화면" in normalized or "desktop" in lower,
            wants_folder="폴더" in normalized or "디렉토리" in normalized,
            wants_file="파일" in normalized or bool(source_path),
            wants_system_info=any(
                token in normalized
                for token in (
                    "시스템 정보", "pc 정보", "컴퓨터 정보", "사양", "process", "프로세스",
                    "시스템 상태", "상태 확인", "상태 점검", "시스템 점검", "헬스 체크", "건강 점검",
                )
            ),
            wants_copy=any(token in normalized for token in ("복사", "copy")),
            wants_move=any(token in normalized for token in ("이동", "옮겨", "move")),
            wants_list=any(token in normalized for token in ("목록", "리스트", "나열", "보여줘")),
            wants_delete=any(token in normalized for token in ("삭제", "지워", "제거")),
            wants_open=any(token in normalized for token in ("열어", "열고", "실행", "켜", "오픈", "launch", "open")),
            wants_login=any(token in normalized for token in ("로그인", "sign in", "login", "log in", "signin")),
            wants_browser=bool(url) or any(token in normalized for token in ("브라우저", "사이트", "웹", "크롬", "엣지")),
            wants_download=any(token in normalized for token in ("다운로드", "download", "내려받", "저장")),
            wants_link_collection=any(token in normalized for token in ("링크", "url 목록", "주소 목록", "링크 수집", "링크 목록", "collect links", "collect link", "gather links", "link list", "links")),
            wants_rename=any(token in normalized for token in ("이름 변경", "이름바꿔", "이름 바꿔", "이름을", "파일명", "rename")),
            wants_merge=any(token in normalized for token in ("병합", "합쳐", "merge")),
            wants_organize=any(token in normalized for token in ("정리", "분류", "확장자별")),
            wants_analyze=any(token in normalized for token in ("분석", "통계", "구조 확인")),
            wants_log_report="로그" in normalized and any(token in normalized for token in ("리포트", "보고", "분석", "요약")),
            wants_security_audit=any(
                token in normalized
                for token in ("보안 점검", "자체 보안 점검", "보안 검사", "보안 진단", "security check", "security audit")
            ),
            wants_type_text=any(token in normalized for token in ("입력", "적어", "써", "작성", "type")),
            wants_window_summary=any(token in normalized for token in ("열린 창", "창 제목", "윈도우 제목", "window title", "window titles")),
            wants_batch_rename=any(token in normalized for token in ("일괄 변경", "일괄변경", "한꺼번에 이름", "규칙 기반 이름", "batch rename")),
            wants_file_set_scan=any(token in normalized for token in ("파일 세트", "대량 파일", "묶음 파일", "확장자 통계")),
            source_path=source_path,
            destination_path=destination_path,
            url=url,
            target_name=target_name,
            preferred_format=preferred_format,
            rename_target=rename_target,
            all_paths=all_paths,
            input_text=input_text,
        )

    def _infer_special_folder_path(self, normalized_goal: str, lower_goal: str) -> str:
        if self.is_developer_goal(normalized_goal):
            return ""
        matched_alias = ""
        for alias in _SPECIAL_FOLDER_ALIASES:
            haystack = lower_goal if alias.isascii() else normalized_goal
            needle = alias if alias.isascii() else alias
            if needle in haystack:
                matched_alias = alias
                break
        if not matched_alias:
            return ""
        folder_name = _SPECIAL_FOLDER_ALIASES[matched_alias]
        if folder_name == "Desktop":
            return os.path.join(os.path.expanduser("~"), folder_name)
        return os.path.join(os.path.expanduser("~"), folder_name)

    def _extract_rename_target(self, goal: str, current_path: str = "") -> str:
        quoted = re.findall(r'["\']([^"\']+)["\']', goal)
        basename = os.path.basename(current_path) if current_path else ""
        for candidate in reversed(quoted):
            if candidate and candidate != current_path and candidate != basename:
                return candidate.strip()

        patterns = [
            r'(?:이름(?:을)?\s*|파일명(?:을)?\s*)([가-힣A-Za-z0-9._-]+)(?:\s*으로)?\s*(?:변경|바꿔)',
            r'([가-힣A-Za-z0-9._-]+)\s*(?:으로|로)\s*이름(?:을)?\s*(?:변경|바꿔)',
            r'([A-Za-z0-9._-]+\.[A-Za-z0-9]+)\s*(?:으로|로)\s*(?:변경|바꿔)',
            r'rename\s+(?:to\s+)?([A-Za-z0-9._-]+)',
        ]
        for pattern in patterns:
            match = re.search(pattern, goal, flags=re.IGNORECASE)
            if match:
                candidate = match.group(1).strip()
                if candidate and candidate != basename:
                    return candidate
        return ""

    def _extract_folder_name(self, goal: str) -> str:
        quoted_match = re.search(r'["\']([^"\']+)["\']\s*폴더', goal)
        if quoted_match:
            return quoted_match.group(1).strip()
        plain_match = re.search(r'([가-힣A-Za-z0-9][가-힣A-Za-z0-9 ._-]{1,80})\s*폴더', goal)
        if plain_match:
            candidate = plain_match.group(1).strip()
            candidate = re.sub(r'^(?:바탕화면(?:에)?|desktop(?:에)?|작업\s*폴더)\s*', '', candidate, flags=re.IGNORECASE).strip()
            if candidate:
                return candidate
        return ""

    def _extract_input_text(self, goal: str, paths: List[str], url: str) -> str:
        quoted = re.findall(r'["\']([^"\']+)["\']', goal)
        excluded = set(paths or [])
        if url:
            excluded.add(url)
        for candidate in quoted:
            cleaned = candidate.strip()
            if cleaned and cleaned not in excluded:
                return cleaned
        typed_match = re.search(r'(?:입력|적어|써|작성)\s*(?:해줘|해)\s*[:：]?\s*([^\n]+)$', goal)
        if typed_match:
            candidate = typed_match.group(1).strip()
            if candidate:
                return candidate
        return ""

    def _build_open_target_plan(self, profile: GoalProfile) -> List[ActionStep]:
        if profile.url:
            content = f"opened = open_url({json.dumps(profile.url)})\nprint(opened)"
            desc = "웹사이트 열기"
        elif profile.source_path:
            src = profile.source_path.replace("\\", "\\\\")
            content = f"opened = open_path(r'{src}')\nprint(opened)"
            desc = "파일/경로 열기"
        else:
            target = profile.target_name if profile.target_name else profile.normalized_goal
            content = f"opened = launch_app({json.dumps(target, ensure_ascii=False)})\nprint(opened)"
            desc = "앱 실행"
        return [
            ActionStep(
                step_id=0,
                step_type="python",
                content=content,
                description_kr=desc,
                expected_output="opened target",
                on_failure="abort",
            ),
        ]

    def _build_browser_download_plan(self, profile: GoalProfile) -> List[ActionStep]:
        folder_name = profile.target_name if profile.target_name not in {"result", "summary"} else "downloads"
        fallback_actions = [
            {"type": "wait_title", "contains": "download", "timeout": 6.0},
            {"type": "wait_title", "contains": "다운로드", "timeout": 6.0},
            {
                "type": "click_text",
                "text_contains": "다운로드",
                "selectors": [
                    "a[download]",
                    "button[download]",
                    "a[href*='download']",
                    "button[id*='download']",
                    ".download",
                    "[aria-label*='다운로드']",
                ],
            },
            {
                "type": "click_text",
                "text_contains": "download",
                "selectors": [
                    "a[download]",
                    "button[download]",
                    "a[href*='download']",
                    "button[id*='download']",
                    ".download",
                    "[aria-label*='download']",
                ],
            },
            {"type": "download_wait", "timeout": 30.0},
            {"type": "read_url"},
        ]
        return [
            ActionStep(
                step_id=0,
                step_type="python",
                content=(
                    "import os\n"
                    f"folder_path = os.path.join(desktop_path, '{folder_name}')\n"
                    "os.makedirs(folder_path, exist_ok=True)\n"
                    "print(folder_path)"
                ),
                description_kr="다운로드 결과 폴더 준비",
                expected_output="folder path",
                on_failure="abort",
            ),
            ActionStep(
                step_id=1,
                step_type="python",
                content=(
                    f"url = {json.dumps(profile.url, ensure_ascii=False)}\n"
                    f"goal_hint = {json.dumps(profile.normalized_goal, ensure_ascii=False)}\n"
                    f"fallback_actions = {json.dumps(fallback_actions, ensure_ascii=False)}\n"
                    "result = run_resilient_browser_workflow(url, goal_hint=goal_hint, fallback_actions=fallback_actions)\n"
                    "print(result)"
                ),
                description_kr="브라우저 상태 열기",
                expected_output="browser state",
                condition="len(step_outputs.get('step_0_output', '')) > 0",
                on_failure="abort",
            ),
            ActionStep(
                step_id=2,
                step_type="think",
                content="",
                description_kr="열린 브라우저 상태를 확인하고 필요한 다운로드 액션을 결정",
                expected_output="",
                condition="len(step_outputs.get('step_1_output', '')) > 0",
                on_failure="continue",
            ),
        ]

    def _build_browser_link_collection_plan(self, profile: GoalProfile) -> List[ActionStep]:
        return [
            ActionStep(
                step_id=0,
                step_type="python",
                content=(
                    f"url = {json.dumps(profile.url, ensure_ascii=False)}\n"
                    f"goal_hint = {json.dumps(profile.normalized_goal, ensure_ascii=False)}\n"
                    "replan_on_dom = True\n"
                    "fallback_actions = [\n"
                    "    {'type': 'read_title'},\n"
                    "    {'type': 'read_url'},\n"
                    "    {'type': 'read_links', 'selector': 'a', 'limit': 12},\n"
                    "]\n"
                    "result = run_resilient_browser_workflow(url, goal_hint=goal_hint, fallback_actions=fallback_actions)\n"
                    "print(result)"
                ),
                description_kr="브라우저 링크 수집",
                expected_output="browser link summary",
                on_failure="abort",
            ),
        ]

    def _build_browser_link_collection_save_plan(self, profile: GoalProfile) -> List[ActionStep]:
        folder_name = profile.target_name if profile.target_name not in {"result", "summary"} else "browser_links"
        title = "브라우저 링크 수집 결과"
        return [
            ActionStep(
                step_id=0,
                step_type="python",
                content=(
                    "import os\n"
                    f"folder_path = os.path.join(desktop_path, '{folder_name}')\n"
                    "os.makedirs(folder_path, exist_ok=True)\n"
                    "print(folder_path)"
                ),
                description_kr="브라우저 링크 저장 폴더 준비",
                expected_output="folder path",
                on_failure="abort",
            ),
            ActionStep(
                step_id=1,
                step_type="python",
                content=(
                    f"url = {json.dumps(profile.url, ensure_ascii=False)}\n"
                    f"goal_hint = {json.dumps(profile.normalized_goal, ensure_ascii=False)}\n"
                    "replan_on_dom = True\n"
                    "fallback_actions = [\n"
                    "    {'type': 'read_title'},\n"
                    "    {'type': 'read_url'},\n"
                    "    {'type': 'read_links', 'selector': 'a', 'limit': 20},\n"
                    "]\n"
                    "result = run_resilient_browser_workflow(url, goal_hint=goal_hint, fallback_actions=fallback_actions)\n"
                    "print(result)"
                ),
                description_kr="브라우저 링크 수집",
                expected_output="browser link summary",
                condition="len(step_outputs.get('step_0_output', '')) > 0",
                on_failure="abort",
            ),
            ActionStep(
                step_id=2,
                step_type="python",
                content=(
                    "folder_path = step_outputs.get('step_0_output', '').strip()\n"
                    "content = step_outputs.get('step_1_output', '')\n"
                    f"saved_path = save_document(folder_path, 'browser_links', content, preferred_format={json.dumps(profile.preferred_format)}, title={json.dumps(title, ensure_ascii=False)})\n"
                    "print(saved_path)"
                ),
                description_kr="브라우저 링크 수집 결과 저장",
                expected_output="saved browser link path",
                condition="len(step_outputs.get('step_1_output', '')) > 0",
                on_failure="abort",
            ),
        ]

    def _build_browser_login_prep_plan(self, profile: GoalProfile) -> List[ActionStep]:
        return [
            ActionStep(
                step_id=0,
                step_type="python",
                content=(
                    f"url = {json.dumps(profile.url, ensure_ascii=False)}\n"
                    f"goal_hint = {json.dumps(profile.normalized_goal, ensure_ascii=False)}\n"
                    "replan_on_dom = True\n"
                    "fallback_actions = [\n"
                    "    {'type': 'read_title'},\n"
                    "    {'type': 'read_url'},\n"
                    "    {'type': 'wait_selector', 'selectors': ['a[href*=login]', 'a[href*=signin]', 'button[id*=login]', 'button[class*=login]']},\n"
                    "    {'type': 'click_text', 'text_contains': '로그인', 'selectors': ['a[href*=login]', 'a[href*=signin]', 'button[id*=login]', 'button[class*=login]', '[aria-label*=로그인]']},\n"
                    "    {'type': 'click_text', 'text_contains': 'login', 'selectors': ['a[href*=login]', 'a[href*=signin]', 'button[id*=login]', 'button[class*=login]', '[aria-label*=login]']},\n"
                    "    {'type': 'read_title'},\n"
                    "    {'type': 'read_url'},\n"
                    "]\n"
                    "result = run_resilient_browser_workflow(url, goal_hint=goal_hint, fallback_actions=fallback_actions)\n"
                    "print(result)"
                ),
                description_kr="브라우저 로그인 진입 준비",
                expected_output="browser login page state",
                on_failure="abort",
            ),
        ]

    def _build_browser_login_and_collect_plan(self, profile: GoalProfile) -> List[ActionStep]:
        return [
            ActionStep(
                step_id=0,
                step_type="python",
                content=(
                    f"url = {json.dumps(profile.url, ensure_ascii=False)}\n"
                    f"goal_hint = {json.dumps(profile.normalized_goal, ensure_ascii=False)}\n"
                    "replan_on_dom = True\n"
                    "fallback_actions = [\n"
                    "    {'type': 'read_title'},\n"
                    "    {'type': 'read_url'},\n"
                    "    {'type': 'click_text', 'text_contains': '로그인', 'selectors': ['a[href*=login]', 'a[href*=signin]', 'button[id*=login]', 'button[class*=login]', '[aria-label*=로그인]']},\n"
                    "    {'type': 'click_text', 'text_contains': 'login', 'selectors': ['a[href*=login]', 'a[href*=signin]', 'button[id*=login]', 'button[class*=login]', '[aria-label*=login]']},\n"
                    "    {'type': 'read_title'},\n"
                    "    {'type': 'read_url'},\n"
                    "    {'type': 'read_links', 'selector': 'a', 'limit': 12},\n"
                    "]\n"
                    "result = run_resilient_browser_workflow(url, goal_hint=goal_hint, fallback_actions=fallback_actions)\n"
                    "print(result)"
                ),
                description_kr="브라우저 로그인 후 링크 수집 준비",
                expected_output="browser login+links result",
                on_failure="abort",
            ),
        ]

    def _build_browser_input_plan(self, profile: GoalProfile) -> List[ActionStep]:
        search_like = any(token in profile.normalized_goal for token in ("검색", "찾아", "query", "검색창"))
        submit_text = "검색" if search_like else "확인"
        submit_text_en = "search" if search_like else "submit"
        return [
            ActionStep(
                step_id=0,
                step_type="python",
                content=(
                    f"url = {json.dumps(profile.url, ensure_ascii=False)}\n"
                    f"goal_hint = {json.dumps(profile.normalized_goal, ensure_ascii=False)}\n"
                    f"input_text = {json.dumps(profile.input_text, ensure_ascii=False)}\n"
                    "fallback_actions = [\n"
                    "    {'type': 'wait_selector', 'selectors': ['input[type=search]', 'input[name=q]', 'input[type=text]', 'textarea']},\n"
                    "    {'type': 'type', 'text': input_text, 'selectors': ['input[type=search]', 'input[name=q]', 'input[type=text]', 'textarea']},\n"
                    f"    {{'type': 'click_text', 'text_contains': {json.dumps(submit_text, ensure_ascii=False)}, 'selectors': ['button[type=submit]', 'input[type=submit]', '.search', '[aria-label*=search]']}},\n"
                    f"    {{'type': 'click_text', 'text_contains': {json.dumps(submit_text_en, ensure_ascii=False)}, 'selectors': ['button[type=submit]', 'input[type=submit]', '.search', '[aria-label*=search]']}},\n"
                    "    {'type': 'read_title'},\n"
                    "    {'type': 'read_url'},\n"
                    "    {'type': 'read_links', 'selector': 'a', 'limit': 8},\n"
                    "]\n"
                    "result = run_resilient_browser_workflow(url, goal_hint=goal_hint, fallback_actions=fallback_actions)\n"
                    "print(result)"
                ),
                description_kr="브라우저 입력 및 후속 상태 확인",
                expected_output="browser input workflow result",
                on_failure="abort",
            ),
        ]

    def _build_browser_input_save_plan(self, profile: GoalProfile) -> List[ActionStep]:
        folder_name = profile.target_name if profile.target_name not in {"result", "summary"} else "browser_result"
        title = "브라우저 입력 결과"
        input_steps = self._build_browser_input_plan(profile)
        browser_step = input_steps[0]
        return [
            ActionStep(
                step_id=0,
                step_type="python",
                content=(
                    "import os\n"
                    f"folder_path = os.path.join(desktop_path, '{folder_name}')\n"
                    "os.makedirs(folder_path, exist_ok=True)\n"
                    "print(folder_path)"
                ),
                description_kr="브라우저 결과 저장 폴더 준비",
                expected_output="folder path",
                on_failure="abort",
            ),
            ActionStep(
                step_id=1,
                step_type=browser_step.step_type,
                content=browser_step.content,
                description_kr=browser_step.description_kr,
                expected_output=browser_step.expected_output,
                condition="len(step_outputs.get('step_0_output', '')) > 0",
                on_failure=browser_step.on_failure,
            ),
            ActionStep(
                step_id=2,
                step_type="python",
                content=(
                    "folder_path = step_outputs.get('step_0_output', '').strip()\n"
                    "content = step_outputs.get('step_1_output', '')\n"
                    f"saved_path = save_document(folder_path, 'browser_result', content, preferred_format={json.dumps(profile.preferred_format)}, title={json.dumps(title, ensure_ascii=False)})\n"
                    "print(saved_path)"
                ),
                description_kr="브라우저 입력 결과 저장",
                expected_output="saved browser result path",
                condition="len(step_outputs.get('step_1_output', '')) > 0",
                on_failure="abort",
            ),
        ]

    def _build_rename_plan(self, profile: GoalProfile) -> List[ActionStep]:
        source = profile.source_path.replace("\\", "\\\\")
        new_name = profile.rename_target.replace("\\", "\\\\")
        return [
            ActionStep(
                step_id=0,
                step_type="python",
                content=(
                    f"result_path = rename_file(r'{source}', {json.dumps(new_name, ensure_ascii=False)})\n"
                    "print(result_path)"
                ),
                description_kr="파일 이름 변경",
                expected_output="renamed path",
                on_failure="abort",
            ),
        ]

    def _build_batch_rename_plan(self, profile: GoalProfile) -> List[ActionStep]:
        escaped_source = profile.source_path.replace("\\", "\\\\") if profile.source_path else ""
        source_expr = f"r'{escaped_source}'" if escaped_source else "desktop_path"
        return [
            ActionStep(
                step_id=0,
                step_type="python",
                content=(
                    "import json\n"
                    f"folder_path = {source_expr}\n"
                    "result = batch_rename_files(folder_path, rename_rule=r'\\s+', replacement='_', dry_run=False)\n"
                    "print(json.dumps(result, ensure_ascii=False))"
                ),
                description_kr="규칙 기반 일괄 이름 변경",
                expected_output="batch rename result",
                on_failure="abort",
            ),
        ]

    def _build_file_set_scan_plan(self, profile: GoalProfile) -> List[ActionStep]:
        escaped_source = profile.source_path.replace("\\", "\\\\") if profile.source_path else ""
        source_expr = f"r'{escaped_source}'" if escaped_source else "desktop_path"
        return [
            ActionStep(
                step_id=0,
                step_type="python",
                content=(
                    "import json\n"
                    f"folder_path = {source_expr}\n"
                    "result = detect_file_set(folder_path)\n"
                    "print(json.dumps(result, ensure_ascii=False))"
                ),
                description_kr="대량 파일 세트 인식",
                expected_output="file set summary",
                on_failure="abort",
            ),
        ]

    def _build_desktop_app_plan(self, profile: GoalProfile) -> List[ActionStep]:
        app_target = profile.target_name if profile.target_name not in {"result", "summary"} else profile.normalized_goal
        window_target = {
            "notepad": "메모장",
            "explorer": "탐색기",
            "chrome": "Chrome",
            "msedge": "Edge",
            "code": "Visual Studio Code",
            "calculator": "계산기",
        }.get(app_target, app_target)
        actions: List[Dict[str, object]] = []
        app_launch_target = app_target
        if app_target == "explorer" and profile.source_path:
            app_launch_target = profile.source_path
        elif app_target in {"chrome", "msedge"} and profile.url:
            app_launch_target = app_target
        if profile.input_text and app_target == "notepad":
            actions.append({"type": "type", "text": profile.input_text, "use_clipboard": True})
        if app_target in {"chrome", "msedge"} and profile.url:
            actions.append({"type": "wait", "seconds": 1.0})
        action_json = json.dumps(actions, ensure_ascii=False)
        content_lines = [
            "import json",
            (
                f"result = run_resilient_desktop_workflow(goal_hint={json.dumps(profile.normalized_goal, ensure_ascii=False)}, "
                f"app_target={json.dumps(app_launch_target, ensure_ascii=False)}, "
                f"expected_window={json.dumps(window_target, ensure_ascii=False)}, "
                f"fallback_actions={action_json})"
            ),
        ]
        if app_target in {"chrome", "msedge"} and profile.url:
            content_lines.append(f"opened_url = open_url({json.dumps(profile.url, ensure_ascii=False)})")
            content_lines.append("result['opened_url'] = opened_url")
        content_lines.append("print(json.dumps(result, ensure_ascii=False))")
        content = "\n".join(content_lines)
        desc = "데스크톱 앱 워크플로우 실행"
        return [
            ActionStep(
                step_id=0,
                step_type="python",
                content=content,
                description_kr=desc,
                expected_output="desktop workflow result",
                on_failure="abort",
            ),
        ]

    def _build_merge_files_plan(self, profile: GoalProfile) -> List[ActionStep]:
        file_paths = profile.all_paths[:]
        output_name = "merged_result.txt"
        if profile.destination_path and profile.destination_path not in file_paths:
            escaped_destination = profile.destination_path.replace("\\", "\\\\")
            output_path_expr = f"r'{escaped_destination}'"
        else:
            output_path_expr = (
                "os.path.join(desktop_path, "
                f"{json.dumps(output_name, ensure_ascii=False)})"
            )

        return [
            ActionStep(
                step_id=0,
                step_type="python",
                content=(
                    "import os\n"
                    f"file_paths = {json.dumps(file_paths, ensure_ascii=False)}\n"
                    f"output_path = {output_path_expr}\n"
                    "os.makedirs(os.path.dirname(output_path) or desktop_path, exist_ok=True)\n"
                    "result_path = merge_files(file_paths, output_path)\n"
                    "print(result_path)"
                ),
                description_kr="텍스트 파일 병합",
                expected_output="merged file path",
                on_failure="abort",
            ),
        ]

    def _build_organize_folder_plan(self, profile: GoalProfile) -> List[ActionStep]:
        escaped_source = profile.source_path.replace("\\", "\\\\") if profile.source_path else ""
        target_expr = f"r'{escaped_source}'" if escaped_source else "desktop_path"
        target_label = profile.source_path or "바탕화면"
        return [
            ActionStep(
                step_id=0,
                step_type="python",
                content=(
                    "import json\n"
                    f"folder_path = {target_expr}\n"
                    "stats = organize_folder(folder_path)\n"
                    "print(json.dumps(stats, ensure_ascii=False))"
                ),
                description_kr=f"{target_label} 확장자별 정리",
                expected_output="organization stats",
                on_failure="abort",
            ),
        ]

    def _build_data_analysis_plan(self, profile: GoalProfile) -> List[ActionStep]:
        source = profile.source_path.replace("\\", "\\\\")
        title = f"{os.path.basename(profile.source_path)} 분석 보고서"
        return [
            ActionStep(
                step_id=0,
                step_type="python",
                content=(
                    "import json\n"
                    f"result = analyze_data(r'{source}')\n"
                    "print(json.dumps(result, ensure_ascii=False))"
                ),
                description_kr="데이터 파일 분석",
                expected_output="analysis json",
                on_failure="abort",
            ),
            ActionStep(
                step_id=1,
                step_type="python",
                content=(
                    "import json\n"
                    "analysis = json.loads(step_outputs.get('step_0_output', '{}') or '{}')\n"
                    f"lines = ['- 파일: {os.path.basename(profile.source_path)}', '']\n"
                    "for key, value in analysis.items():\n"
                    "    lines.append(f'- {key}: {value}')\n"
                    "report_body = '\\n'.join(lines)\n"
                    f"output_path = os.path.join(desktop_path, {json.dumps(profile.target_name or 'analysis_report', ensure_ascii=False)} + '.md')\n"
                    f"saved_path = generate_report(report_body, output_path, title={json.dumps(title, ensure_ascii=False)})\n"
                    "print(saved_path)"
                ),
                description_kr="분석 보고서 저장",
                expected_output="saved analysis report path",
                condition="len(step_outputs.get('step_0_output', '')) > 0",
                on_failure="abort",
            ),
        ]

    def _build_log_report_plan(self, profile: GoalProfile) -> List[ActionStep]:
        source = profile.source_path.replace("\\", "\\\\")
        title = f"{os.path.basename(profile.source_path)} 로그 리포트"
        return [
            ActionStep(
                step_id=0,
                step_type="python",
                content=(
                    f"log_path = r'{source}'\n"
                    "with open(log_path, 'r', encoding='utf-8', errors='ignore') as handle:\n"
                    "    lines = handle.readlines()\n"
                    "error_count = sum(1 for line in lines if 'ERROR' in line)\n"
                    "warning_count = sum(1 for line in lines if 'WARNING' in line)\n"
                    "info_count = sum(1 for line in lines if 'INFO' in line)\n"
                    "tail = ''.join(lines[-20:]).strip()\n"
                    "report_body = '\\n'.join([\n"
                    "    f'- 총 라인 수: {len(lines)}',\n"
                    "    f'- ERROR: {error_count}',\n"
                    "    f'- WARNING: {warning_count}',\n"
                    "    f'- INFO: {info_count}',\n"
                    "    '',\n"
                    "    '## 최근 로그',\n"
                    "    '```',\n"
                    "    tail,\n"
                    "    '```',\n"
                    "])\n"
                    "print(report_body)"
                ),
                description_kr="로그 요약 생성",
                expected_output="log summary markdown",
                on_failure="abort",
            ),
            ActionStep(
                step_id=1,
                step_type="python",
                content=(
                    "report_body = step_outputs.get('step_0_output', '')\n"
                    f"output_path = os.path.join(desktop_path, {json.dumps(profile.target_name or 'log_report', ensure_ascii=False)} + '.md')\n"
                    f"saved_path = generate_report(report_body, output_path, title={json.dumps(title, ensure_ascii=False)})\n"
                    "print(saved_path)"
                ),
                description_kr="로그 리포트 저장",
                expected_output="saved log report path",
                condition="len(step_outputs.get('step_0_output', '')) > 0",
                on_failure="abort",
            ),
        ]

    def _build_create_folder_plan(self, profile: GoalProfile) -> List[ActionStep]:
        folder_name = profile.target_name or "new_folder"
        return [
            ActionStep(
                step_id=0,
                step_type="python",
                content=(
                    "import os\n"
                    f"folder_path = os.path.join(desktop_path, {json.dumps(folder_name, ensure_ascii=False)})\n"
                    "os.makedirs(folder_path, exist_ok=True)\n"
                    "print(folder_path)"
                ),
                description_kr="폴더 생성",
                expected_output="created folder path",
                on_failure="abort",
            ),
        ]

    def _build_window_summary_save_plan(self, profile: GoalProfile) -> List[ActionStep]:
        folder_name = profile.target_name or "window_summary"
        report_title = f"{folder_name} 창 제목 요약 보고서"
        return [
            ActionStep(
                step_id=0,
                step_type="python",
                content=(
                    "import os\n"
                    f"folder_path = os.path.join(desktop_path, {json.dumps(folder_name, ensure_ascii=False)})\n"
                    "os.makedirs(folder_path, exist_ok=True)\n"
                    "print(folder_path)"
                ),
                description_kr="작업 폴더 준비",
                expected_output="created folder path",
                on_failure="abort",
            ),
            ActionStep(
                step_id=1,
                step_type="python",
                content=(
                    "import json\n"
                    "import os\n"
                    "import re\n"
                    "from datetime import datetime\n"
                    "folder_path = step_outputs.get('step_0_output', '').strip()\n"
                    "if not folder_path:\n"
                    "    raise RuntimeError('작업 폴더를 준비하지 못했습니다.')\n"
                    "window_titles = [str(title).strip() for title in list_open_windows(limit=20) if str(title).strip()]\n"
                    "active_title = (get_active_window_title() or '').strip()\n"
                    "target_path = os.path.join(folder_path, 'summary.md')\n"
                    "target_existed = os.path.exists(target_path)\n"
                    "backup_before = len(get_backup_history())\n"
                    "browser_markers = ('chrome', 'whale', 'edge', 'msedge', 'firefox', 'safari', 'opera', '브라우저')\n"
                    "service_aliases = {\n"
                    "    'github': 'GitHub',\n"
                    "    'google': 'Google',\n"
                    "    'youtube': 'YouTube',\n"
                    "    'naver': 'Naver',\n"
                    "    'daum': 'Daum',\n"
                    "    'discord': 'Discord',\n"
                    "    'notion': 'Notion',\n"
                    "    'whale': 'Whale',\n"
                    "    'chrome': 'Chrome',\n"
                    "    'edge': 'Edge',\n"
                    "    'msedge': 'Edge',\n"
                    "}\n"
                    "app_aliases = {\n"
                    "    '파일 탐색기': '파일 관리',\n"
                    "    'explorer': '파일 관리',\n"
                    "    '설정': '시스템',\n"
                    "    'windows 입력 환경': '시스템',\n"
                    "    '카카오톡': '메신저',\n"
                    "    'discord': '메신저',\n"
                    "    'code': '개발 도구',\n"
                    "    'codex': '개발 도구',\n"
                    "    'pythonw': '개발 도구',\n"
                    "}\n"
                    "browser_groups = {}\n"
                    "app_groups = {}\n"
                    "service_tab_hints = {}\n"
                    "tab_estimation_source = {}\n"
                    "chromium_process_map = {\n"
                    "    'Whale': 'whale.exe',\n"
                    "    'Chrome': 'chrome.exe',\n"
                    "    'Edge': 'msedge.exe',\n"
                    "    'Opera': 'opera.exe',\n"
                    "    '기타 브라우저': '',\n"
                    "}\n"
                    "def estimate_tabs_from_process(service: str) -> int:\n"
                    "    exe_name = chromium_process_map.get(service, '')\n"
                    "    if not exe_name:\n"
                    "        return 0\n"
                    "    try:\n"
                    "        import psutil\n"
                    "    except Exception:\n"
                    "        return 0\n"
                    "    renderer_count = 0\n"
                    "    for proc in psutil.process_iter(['name', 'cmdline']):\n"
                    "        name = str((proc.info.get('name') or '')).lower()\n"
                    "        if name != exe_name:\n"
                    "            continue\n"
                    "        cmdline = ' '.join(proc.info.get('cmdline') or []).lower()\n"
                    "        if '--type=renderer' in cmdline and '--extension-process' not in cmdline:\n"
                    "            renderer_count += 1\n"
                    "    if renderer_count <= 0:\n"
                    "        return 0\n"
                    "    if service in {'Whale', 'Chrome', 'Edge', 'Opera'}:\n"
                    "        return max(1, renderer_count - 1)\n"
                    "    return renderer_count\n"
                    "def infer_tab_count(title: str) -> int:\n"
                    "    extra_match = re.search(r'(?:및|외)\\s*(\\d+)\\s*개\\s*탭', title)\n"
                    "    if extra_match:\n"
                    "        return int(extra_match.group(1)) + 1\n"
                    "    total_match = re.search(r'(\\d+)\\s*개\\s*탭', title)\n"
                    "    if total_match:\n"
                    "        return int(total_match.group(1))\n"
                    "    lower_title = title.lower()\n"
                    "    match = re.search(r'tabs?\\s*(\\d+)', lower_title)\n"
                    "    if match:\n"
                    "        return int(match.group(1))\n"
                    "    match = re.search(r'(\\d+)\\s*tabs?', lower_title)\n"
                    "    if match:\n"
                    "        return int(match.group(1))\n"
                    "    return 0\n"
                    "def looks_like_browser_title(title: str) -> bool:\n"
                    "    lowered = title.lower()\n"
                    "    if '브라우저' in lowered:\n"
                    "        return True\n"
                    "    if re.search(r'\\b(whale|chrome|msedge|edge|firefox|safari|opera)\\b', lowered):\n"
                    "        return True\n"
                    "    if ' - ' in title:\n"
                    "        tail = title.rsplit(' - ', 1)[-1].strip().lower()\n"
                    "        if tail in {'whale', 'chrome', 'edge', 'msedge', 'firefox', 'safari', 'opera'}:\n"
                    "            return True\n"
                    "    return False\n"
                    "def detect_browser_service(title: str) -> str:\n"
                    "    lowered = title.lower()\n"
                    "    for alias, service in service_aliases.items():\n"
                    "        if alias in lowered:\n"
                    "            return service\n"
                    "    if ' - ' in title:\n"
                    "        tail = title.rsplit(' - ', 1)[-1].strip()\n"
                    "        if len(tail) >= 2:\n"
                    "            return tail\n"
                    "    if '|' in title:\n"
                    "        tail = title.rsplit('|', 1)[-1].strip()\n"
                    "        if len(tail) >= 2:\n"
                    "            return tail\n"
                    "    return '기타 브라우저'\n"
                    "def detect_app_type(title: str) -> str:\n"
                    "    lowered = title.lower()\n"
                    "    for alias, app_type in app_aliases.items():\n"
                    "        if alias.lower() in lowered:\n"
                    "            return app_type\n"
                    "    if '메모장' in title:\n"
                    "        return '문서 편집'\n"
                    "    if 'terminal' in lowered or 'powershell' in lowered or 'cmd' in lowered:\n"
                    "        return '터미널'\n"
                    "    return '기타 앱'\n"
                    "for title in window_titles:\n"
                    "    is_browser = looks_like_browser_title(title)\n"
                    "    if is_browser:\n"
                    "        service = detect_browser_service(title)\n"
                    "        browser_groups.setdefault(service, []).append(title)\n"
                    "        hinted = infer_tab_count(title)\n"
                    "        if hinted > 0:\n"
                    "            service_tab_hints[service] = max(service_tab_hints.get(service, 0), hinted)\n"
                    "    else:\n"
                    "        app_type = detect_app_type(title)\n"
                    "        app_groups.setdefault(app_type, []).append(title)\n"
                    "estimated_tabs_by_service = {}\n"
                    "for service, titles in browser_groups.items():\n"
                    "    title_hint = service_tab_hints.get(service, 0)\n"
                    "    process_hint = estimate_tabs_from_process(service)\n"
                    "    if process_hint > title_hint:\n"
                    "        estimated_tabs_by_service[service] = process_hint\n"
                    "        tab_estimation_source[service] = 'process'\n"
                    "    elif title_hint > 0:\n"
                    "        estimated_tabs_by_service[service] = title_hint\n"
                    "        tab_estimation_source[service] = 'title'\n"
                    "    else:\n"
                    "        estimated_tabs_by_service[service] = len(titles)\n"
                    "        tab_estimation_source[service] = 'window'\n"
                    "estimated_tabs_total = sum(estimated_tabs_by_service.values())\n"
                    "lines = [\n"
                    f"    '# {report_title}',\n"
                    "    '',\n"
                    "    f'*생성 일시: {datetime.now().strftime(\"%Y-%m-%d %H:%M:%S\")}*',\n"
                    "    '',\n"
                    "    '## 브라우저 관련 창 (서비스 기준)',\n"
                    "]\n"
                    "if browser_groups:\n"
                    "    for service, titles in sorted(browser_groups.items(), key=lambda item: (-len(item[1]), item[0])):\n"
                    "        lines.append(f'### {service} ({len(titles)})')\n"
                    "        lines.extend(f'- {title}' for title in titles)\n"
                    "        lines.append('')\n"
                    "else:\n"
                    "    lines.append('- 감지된 브라우저 창이 없습니다.')\n"
                    "lines.extend([\n"
                    "    '',\n"
                    "    '## 일반 앱 창 (앱 종류 기준)',\n"
                    "])\n"
                    "if app_groups:\n"
                    "    for app_type, titles in sorted(app_groups.items(), key=lambda item: (-len(item[1]), item[0])):\n"
                    "        lines.append(f'### {app_type} ({len(titles)})')\n"
                    "        lines.extend(f'- {title}' for title in titles)\n"
                    "        lines.append('')\n"
                    "else:\n"
                    "    lines.append('- 감지된 일반 앱 창이 없습니다.')\n"
                    "lines.extend([\n"
                    "    '',\n"
                    "    '## 브라우저 탭 추정',\n"
                    "])\n"
                    "if estimated_tabs_by_service:\n"
                    "    for service, tab_count in sorted(estimated_tabs_by_service.items(), key=lambda item: (-item[1], item[0])):\n"
                    "        source = tab_estimation_source.get(service, 'window')\n"
                    "        source_kr = '프로세스 기반' if source == 'process' else ('제목 기반' if source == 'title' else '창 개수 기반')\n"
                    "        lines.append(f'- {service}: {tab_count}개 ({source_kr})')\n"
                    "else:\n"
                    "    lines.append('- 탭 수를 추정할 브라우저 창이 없습니다.')\n"
                    "lines.extend([\n"
                    "    '',\n"
                    "    '## 원본 창 제목 목록',\n"
                    "])\n"
                    "if window_titles:\n"
                    "    lines.extend(f'- {title}' for title in window_titles)\n"
                    "else:\n"
                    "    lines.append('- 감지된 열린 창이 없습니다.')\n"
                    "lines.extend([\n"
                    "    '',\n"
                    "    '## 선택한 전략',\n"
                    "    '- `list_open_windows()`로 열린 창 제목을 수집한 뒤 브라우저/일반 앱으로 분류했습니다.',\n"
                    "    '- 브라우저 창은 제목의 서비스 키워드로 그룹핑하고, 탭 수는 제목/프로세스 단서를 함께 사용해 추정했습니다.',\n"
                    "    '- 요청한 폴더를 먼저 준비한 뒤 그 안에 markdown 보고서를 저장했습니다.',\n"
                    "    '- 기존 `summary.md`가 있으면 `save_document()`의 자동 백업을 사용하도록 했습니다.',\n"
                    "    '',\n"
                    "    '## 검증한 내용',\n"
                    "    f'- 폴더 존재 확인: {folder_path}',\n"
                    "    f'- 활성 창 제목 확인: {active_title or \"없음\"}',\n"
                    "    f'- 감지된 창 개수: {len(window_titles)}',\n"
                    "    f'- 브라우저 그룹 수: {len(browser_groups)}',\n"
                    "    f'- 일반 앱 그룹 수: {len(app_groups)}',\n"
                    "    f'- 최종 추정 탭 수: {estimated_tabs_total if estimated_tabs_total > 0 else \"확인 불가\"}',\n"
                    "])\n"
                    "provisional = '\\n'.join(lines).strip() + '\\n'\n"
                    f"saved_path = save_document(folder_path, 'summary', provisional, preferred_format={json.dumps(profile.preferred_format)}, title={json.dumps(report_title, ensure_ascii=False)})\n"
                    "new_backups = get_backup_history()[backup_before:]\n"
                    "backup_created = any(os.path.abspath(item.get('target_path', '')) == os.path.abspath(saved_path) for item in new_backups)\n"
                    "lines.extend([\n"
                    "    '',\n"
                    "    '## 백업 및 덮어쓰기',\n"
                    "    f'- 기존 파일 존재: {\"예\" if target_existed else \"아니오\"}',\n"
                    "    f'- 자동 백업 생성: {\"예\" if backup_created else (\"불필요\" if not target_existed else \"확인 실패\")}',\n"
                    "])\n"
                    "final_content = '\\n'.join(lines).strip() + '\\n'\n"
                    "with open(saved_path, 'w', encoding='utf-8') as handle:\n"
                    "    handle.write(final_content)\n"
                    "print(json.dumps({\n"
                    "    'folder_path': folder_path,\n"
                    "    'saved_path': saved_path,\n"
                    "    'window_count': len(window_titles),\n"
                    "    'browser_group_count': len(browser_groups),\n"
                    "    'app_group_count': len(app_groups),\n"
                    "    'estimated_tabs': estimated_tabs_total,\n"
                    "    'estimated_tabs_by_service': estimated_tabs_by_service,\n"
                    "    'backup_created': backup_created,\n"
                    "    'active_title': active_title,\n"
                    "}, ensure_ascii=False))"
                ),
                description_kr="창 제목 요약 보고서 저장",
                expected_output="window summary report json",
                condition="len(step_outputs.get('step_0_output', '')) > 0",
                on_failure="abort",
            ),
        ]

    def _build_copy_move_plan(self, profile: GoalProfile, move: bool = False) -> List[ActionStep]:
        verb = "이동" if move else "복사"
        func = "shutil.move" if move else "shutil.copy2"
        source = profile.source_path.replace("\\", "\\\\")
        dest = profile.destination_path.replace("\\", "\\\\")
        return [
            ActionStep(
                step_id=0,
                step_type="python",
                content=(
                    "import os\n"
                    "import shutil\n"
                    f"source_path = r'{source}'\n"
                    f"destination_path = r'{dest}'\n"
                    "dest_dir = destination_path if os.path.isdir(destination_path) else os.path.dirname(destination_path)\n"
                    "if dest_dir:\n"
                    "    os.makedirs(dest_dir, exist_ok=True)\n"
                    f"result_path = {func}(source_path, destination_path)\n"
                    "print(result_path)"
                ),
                description_kr=f"파일 {verb}",
                expected_output=f"{verb}된 경로",
                on_failure="abort",
            ),
        ]

    def _build_system_info_plan(self, profile: GoalProfile) -> List[ActionStep]:
        folder_name = profile.target_name if profile.target_name not in {"result", "summary"} else "system_report"
        title = "기본 보안 점검 보고서" if profile.wants_security_audit else "시스템 정보 보고서"
        heading = "# 기본 보안 점검 보고서" if profile.wants_security_audit else "# 시스템 정보 보고서"
        steps: List[ActionStep] = []

        if profile.wants_save:
            steps.append(
                ActionStep(
                    step_id=0,
                    step_type="python",
                    content=(
                        "import os\n"
                        f"folder_path = os.path.join(desktop_path, '{folder_name}')\n"
                        "os.makedirs(folder_path, exist_ok=True)\n"
                        "print(folder_path)"
                    ),
                    description_kr="보고서 폴더 준비",
                    expected_output="folder path",
                    on_failure="abort",
                )
            )

        gather_step_id = len(steps)
        gather_condition = "len(step_outputs.get('step_0_output', '')) > 0" if profile.wants_save else ""
        gather_lines = [
            "import os",
            "import platform",
            "import psutil",
            f"lines = [{json.dumps(heading, ensure_ascii=False)}, '']",
            "lines.append(f'- OS: {platform.platform()}')",
            "lines.append(f'- Python: {platform.python_version()}')",
            "lines.append(f'- CPU 코어: {psutil.cpu_count(logical=True)}')",
            "vm = psutil.virtual_memory()",
            "lines.append(f'- 메모리: {round(vm.total / (1024**3), 2)} GB')",
            "disk = psutil.disk_usage(os.path.expanduser('~'))",
            "lines.append(f'- 디스크 사용률: {disk.percent}%')",
            "lines.append('')",
        ]
        if profile.wants_security_audit:
            gather_lines.extend([
                "import ctypes",
                "import subprocess",
                "lines.append('## 기본 보안 점검')",
                "try:",
                "    is_admin = bool(ctypes.windll.shell32.IsUserAnAdmin())",
                "except Exception:",
                "    is_admin = False",
                "lines.append(f'- 관리자 권한 실행 여부: {is_admin}')",
                "defender_running = any((proc.info.get('name') or '').lower() == 'msmpeng.exe' for proc in psutil.process_iter(['name']))",
                "defender_status = '실행 중' if defender_running else '확인되지 않음'",
                "lines.append(f'- Windows Defender 프로세스: {defender_status}')",
                "if os.name == 'nt':",
                "    try:",
                "        firewall = subprocess.run(['netsh', 'advfirewall', 'show', 'allprofiles', 'state'], capture_output=True, text=True, timeout=8)",
                "        firewall_lines = [line.strip() for line in firewall.stdout.splitlines() if 'State' in line or '상태' in line]",
                "        if firewall_lines:",
                "            lines.append('- 방화벽 상태: ' + '; '.join(firewall_lines[:3]))",
                "        else:",
                "            lines.append('- 방화벽 상태: 출력 없음')",
                "    except Exception as exc:",
                "        lines.append(f'- 방화벽 상태 확인 실패: {exc}')",
                "else:",
                "    lines.append('- 방화벽 상태: Windows 전용 점검 항목')",
                "lines.append('')",
            ])
        gather_lines.extend([
            "lines.append('## 실행 중 프로세스 상위 10개')",
            "for proc in sorted(psutil.process_iter(['name', 'memory_info']), key=lambda p: (p.info['memory_info'].rss if p.info['memory_info'] else 0), reverse=True)[:10]:",
            "    mem = proc.info['memory_info'].rss / (1024**2) if proc.info['memory_info'] else 0",
            "    lines.append(f'- {proc.info[\"name\"]}: {mem:.1f} MB')",
            "report = '\\n'.join(lines)",
            "print(report)",
        ])
        steps.append(
            ActionStep(
                step_id=gather_step_id,
                step_type="python",
                content="\n".join(gather_lines),
                description_kr="기본 보안 점검 수행" if profile.wants_security_audit else "시스템 상태 점검",
                expected_output="system info markdown",
                condition=gather_condition,
                on_failure="abort",
            )
        )

        if profile.wants_save:
            steps.append(
                ActionStep(
                    step_id=gather_step_id + 1,
                    step_type="python",
                    content=(
                        "folder_path = step_outputs.get('step_0_output', '').strip()\n"
                        f"report = step_outputs.get('step_{gather_step_id}_output', '')\n"
                        f"saved_path = save_document(folder_path, 'system_report', report, preferred_format={json.dumps(profile.preferred_format)}, title={json.dumps(title, ensure_ascii=False)})\n"
                        "print(saved_path)"
                    ),
                    description_kr="시스템 정보 저장",
                    expected_output="saved report path",
                    condition=f"len(step_outputs.get('step_{gather_step_id}_output', '')) > 0",
                    on_failure="abort",
                )
            )

        return steps

    def _build_directory_listing_plan(self, profile: GoalProfile) -> List[ActionStep]:
        source = profile.source_path.replace("\\", "\\\\") if profile.source_path else ""
        title = "디렉터리 목록"
        target_line = f"target_path = r'{source}'\n" if source else "target_path = desktop_path\n"
        return [
            ActionStep(
                step_id=0,
                step_type="python",
                content=(
                    "import os\n"
                    f"{target_line}"
                    "entries = []\n"
                    "for name in sorted(os.listdir(target_path))[:500]:\n"
                    "    full = os.path.join(target_path, name)\n"
                    "    kind = 'dir' if os.path.isdir(full) else 'file'\n"
                    "    entries.append(f'- [{kind}] {name}')\n"
                    "content = '# 디렉터리 목록\\n\\n' + '\\n'.join(entries)\n"
                    "print(content)"
                ),
                description_kr="디렉터리 목록 생성",
                expected_output="directory listing markdown",
                on_failure="abort",
            ),
            ActionStep(
                step_id=1,
                step_type="python",
                content=(
                    "folder_path = os.path.join(desktop_path, 'directory_listing')\n"
                    "os.makedirs(folder_path, exist_ok=True)\n"
                    "content = step_outputs.get('step_0_output', '')\n"
                    f"saved_path = save_document(folder_path, 'directory_listing', content, preferred_format={json.dumps(profile.preferred_format)}, title={json.dumps(title, ensure_ascii=False)})\n"
                    "print(saved_path)"
                ),
                description_kr="디렉터리 목록 저장",
                expected_output="saved listing path",
                condition="len(step_outputs.get('step_0_output', '')) > 0",
                on_failure="abort",
            ),
        ]

    def _build_file_summary_plan(self, profile: GoalProfile) -> List[ActionStep]:
        source_path = profile.source_path.replace("\\", "\\\\")
        output_folder = profile.target_name if profile.target_name else "summary"
        return [
            ActionStep(
                step_id=0,
                step_type="python",
                content=(
                    "import os\n"
                    f"folder_path = os.path.join(desktop_path, '{output_folder}')\n"
                    "os.makedirs(folder_path, exist_ok=True)\n"
                    "print(folder_path)"
                ),
                description_kr="출력 폴더 준비",
                expected_output="폴더 경로",
                on_failure="abort",
            ),
            ActionStep(
                step_id=1,
                step_type="python",
                content=(
                    f"source_path = r'{source_path}'\n"
                    "with open(source_path, 'r', encoding='utf-8') as f:\n"
                    "    content = f.read()\n"
                    "print(content[:12000])"
                ),
                description_kr="원본 파일 읽기",
                expected_output="source file content",
                condition="len(step_outputs.get('step_0_output', '')) > 0",
                on_failure="abort",
            ),
            ActionStep(
                step_id=2,
                step_type="python",
                content=(
                    "content = step_outputs.get('step_1_output', '')\n"
                    "paragraphs = [p.strip() for p in content.split('\\n') if p.strip()]\n"
                    "summary_lines = ['# 문서 요약', '']\n"
                    "summary_lines.append(f'- 원본 길이: {len(content)}자')\n"
                    "summary_lines.append('')\n"
                    "for idx, paragraph in enumerate(paragraphs[:5], 1):\n"
                    "    summary_lines.append(f'## 핵심 {idx}')\n"
                    "    summary_lines.append(f'- {paragraph[:300]}')\n"
                    "    summary_lines.append('')\n"
                    "summary = '\\n'.join(summary_lines).strip()\n"
                    "print(summary)"
                ),
                description_kr="문서 요약",
                expected_output="markdown summary text",
                condition="len(step_outputs.get('step_1_output', '')) > 0",
                on_failure="abort",
            ),
            ActionStep(
                step_id=3,
                step_type="python",
                content=(
                    "folder_path = step_outputs.get('step_0_output', '').strip()\n"
                    "summary = step_outputs.get('step_2_output', '')\n"
                    "saved_path = save_document(folder_path, 'file_summary', summary, preferred_format='auto', title='문서 요약')\n"
                    "print(saved_path)"
                ),
                description_kr="요약 저장",
                expected_output="saved summary path",
                condition="len(step_outputs.get('step_2_output', '')) > 0",
                on_failure="abort",
            ),
        ]

    def _build_search_save_plan(self, profile: GoalProfile) -> List[ActionStep]:
        folder_name = profile.target_name if profile.target_name else "result"
        query = "오늘 한국 주요 뉴스" if profile.wants_news else profile.normalized_goal
        summary_title = "오늘 뉴스 요약" if profile.wants_news else "검색 결과 요약"
        raw_title = "오늘 뉴스 검색 결과" if profile.wants_news else "검색 결과"
        raw_file = "news_search" if profile.wants_news else "search_results"
        summary_file = "summary"

        search_step_name = "오늘 뉴스 검색" if profile.wants_news else "웹 검색"
        summary_step_name = "뉴스 요약" if profile.wants_news else "검색 결과 요약"

        return [
            ActionStep(
                step_id=0,
                step_type="python",
                content=(
                    "import os\n"
                    f"folder_path = os.path.join(desktop_path, '{folder_name}')\n"
                    "os.makedirs(folder_path, exist_ok=True)\n"
                    "print(folder_path)"
                ),
                description_kr="바탕화면에 폴더 만들기" if profile.wants_desktop or profile.wants_folder else "작업 폴더 준비",
                expected_output="폴더 경로",
                on_failure="abort",
            ),
            ActionStep(
                step_id=1,
                step_type="python",
                content=(
                    f"query = {json.dumps(query, ensure_ascii=False)}\n"
                    "results = web_search(query, max_results=5)\n"
                    "print(results)"
                ),
                description_kr=search_step_name,
                expected_output="검색 결과 텍스트",
                condition="len(step_outputs.get('step_0_output', '')) > 0",
                on_failure="abort",
            ),
            ActionStep(
                step_id=2,
                step_type="python",
                content=(
                    "folder_path = step_outputs.get('step_0_output', '').strip()\n"
                    "results_text = step_outputs.get('step_1_output', '')\n"
                    "if not folder_path or not results_text or '검색 오류' in results_text or '웹 검색 불가' in results_text or '검색 결과가 없습니다.' in results_text:\n"
                    "    raise RuntimeError('검색 결과를 저장할 수 없습니다.')\n"
                    f"raw_content = '# {raw_title}\\n\\n' + results_text\n"
                    f"raw_path = save_document(folder_path, '{raw_file}', raw_content, preferred_format='md', title={json.dumps(raw_title, ensure_ascii=False)})\n"
                    "print(raw_path)"
                ),
                description_kr="검색 결과 저장",
                expected_output="raw search file path",
                condition="len(step_outputs.get('step_1_output', '')) > 0",
                on_failure="abort",
            ),
            ActionStep(
                step_id=3,
                step_type="python",
                content=(
                    "import re\n"
                    "results_text = step_outputs.get('step_1_output', '')\n"
                    "lines = [line.strip() for line in results_text.splitlines() if line.strip()]\n"
                    "items = []\n"
                    "current = {}\n"
                    "for line in lines:\n"
                    "    if re.match(r'^\\[\\d+\\]', line):\n"
                    "        if current:\n"
                    "            items.append(current)\n"
                    "        current = {'title': re.sub(r'^\\[\\d+\\]\\s*', '', line).strip(), 'snippet': '', 'url': ''}\n"
                    "    elif line.startswith('URL:'):\n"
                    "        current['url'] = line.replace('URL:', '', 1).strip()\n"
                    "    elif current and not current.get('snippet'):\n"
                    "        current['snippet'] = line.strip()\n"
                    "if current:\n"
                    "    items.append(current)\n"
                    "articles = []\n"
                    "for item in items[:3]:\n"
                    "    fetched = ''\n"
                    "    url = item.get('url', '')\n"
                    "    if url:\n"
                    "        fetched = web_fetch(url, max_chars=2400)\n"
                    "    fetched = fetched.replace('\\r', ' ').replace('\\n', ' ').strip()\n"
                    "    if fetched.startswith('페이지 로드 오류:'):\n"
                    "        fetched = ''\n"
                    "    body = item.get('snippet', '')\n"
                    "    detail = fetched[:700] if fetched else body[:260]\n"
                    "    articles.append({'title': item.get('title', '제목 없음'), 'url': url, 'summary': detail})\n"
                    f"summary_lines = ['# {summary_title}', '']\n"
                    "for idx, article in enumerate(articles, 1):\n"
                    "    summary_lines.append(f'## {idx}. {article[\"title\"]}')\n"
                    "    summary_lines.append(f'- 핵심: {article[\"summary\"]}')\n"
                    "    if article['url']:\n"
                    "        summary_lines.append(f'- 링크: {article[\"url\"]}')\n"
                    "    summary_lines.append('')\n"
                    "if not articles:\n"
                    "    raise RuntimeError('요약할 항목을 만들지 못했습니다.')\n"
                    "summary = '\\n'.join(summary_lines).strip()\n"
                    "print(summary)"
                ),
                description_kr=summary_step_name,
                expected_output="markdown summary text",
                condition="len(step_outputs.get('step_1_output', '')) > 0 and '검색 오류' not in step_outputs.get('step_1_output', '') and '검색 결과가 없습니다.' not in step_outputs.get('step_1_output', '')",
                on_failure="abort",
            ),
            ActionStep(
                step_id=4,
                step_type="python",
                content=(
                    "folder_path = step_outputs.get('step_0_output', '').strip()\n"
                    "summary = step_outputs.get('step_3_output', '')\n"
                    "if not folder_path or not summary:\n"
                    "    raise RuntimeError('요약 저장에 필요한 데이터가 없습니다.')\n"
                    f"summary_path = save_document(folder_path, '{summary_file}', summary, preferred_format={json.dumps(profile.preferred_format)}, title={json.dumps(summary_title, ensure_ascii=False)})\n"
                    "plain_summary = '\\n'.join(line[2:] if line.startswith('- ') else line for line in summary.splitlines() if not line.startswith('#'))\n"
                    "text_path = save_document(folder_path, 'summary_plain', plain_summary.strip(), preferred_format='txt', title='요약 평문')\n"
                    "print(summary_path + '\\n' + text_path)"
                ),
                description_kr="요약 저장",
                expected_output="summary file path(s)",
                condition="len(step_outputs.get('step_3_output', '')) > 0",
                on_failure="abort",
            ),
        ]

    def fix_step(
        self,
        step: ActionStep,
        error: str,
        goal: str,
        context: Dict[str, str] = None,
    ) -> Optional[ActionStep]:
        """실패한 단계를 LLM으로 수정 (execution_model 사용)"""
        # 과거 실패 패턴도 힌트로 제공
        failure_hints = self._get_failure_hints(goal)
        ctx_block = self._fmt_context(context)
        if failure_hints:
            ctx_block += f"\n## 이전 실패 패턴 (반복 금지):\n{failure_hints}\n"

        prompt = _FIX_PROMPT.format(
            content=step.content,
            error=error[:500],
            goal=goal,
            context_block=ctx_block,
        )
        raw = self._call_llm(prompt, model=self.llm.execution_model,
                             client_override=self.llm.execution_client,
                             provider_override=self.llm.execution_provider,
                             role_hint="execution")
        self._write_trace("fix_step", goal, raw)
        data = self._parse_object(raw)
        if not data or not data.get("content"):
            logging.warning(f"[Planner] fix_step 파싱 실패: {raw[:200]}")
            heuristic = self._heuristic_fix_step(step, error, goal, context)
            if heuristic:
                return heuristic
            return None
        if self.is_developer_goal(goal):
            disallowed_reason = self._find_disallowed_developer_reason(data.get("content", ""), goal=goal, context=context)
            if disallowed_reason:
                logging.warning(f"[Planner] 개발용 수정안 거부 ({disallowed_reason})")
                heuristic = self._heuristic_fix_step(step, error, goal, context)
                if heuristic:
                    return heuristic
                return None
        return ActionStep(
            step_id=step.step_id,
            step_type=data.get("step_type", step.step_type),
            content=data["content"],
            description_kr=data.get("description_kr", "수정된 코드"),
            expected_output=data.get("expected_output", ""),
            condition=step.condition,
            on_failure=step.on_failure,
        )

    def _heuristic_fix_step(
        self,
        step: ActionStep,
        error: str,
        goal: str,
        context: Dict[str, str] = None,
    ) -> Optional[ActionStep]:
        """LLM 수정안이 깨졌을 때 적용하는 규칙 기반 복구."""
        content = step.content or ""
        normalized_error = (error or "").lower()
        normalized_goal = goal or ""

        if "검색 결과를 저장할 수 없습니다" in error and any(token in normalized_goal for token in ("검색", "뉴스", "웹")):
            return ActionStep(
                step_id=step.step_id,
                step_type="python",
                content=(
                    "folder_path = step_outputs.get('step_0_output', '').strip()\n"
                    "results_text = step_outputs.get('step_1_output', '')\n"
                    "if not folder_path:\n"
                    "    raise RuntimeError('저장 경로가 없습니다.')\n"
                    "fallback_content = '# 검색 결과\\n\\n' + (results_text or '검색 결과를 가져오지 못했습니다.')\n"
                    "saved_path = save_document(folder_path, 'search_results_fallback', fallback_content, preferred_format='md', title='검색 결과')\n"
                    "print(saved_path)"
                ),
                description_kr="검색 결과 폴백 저장",
                expected_output="fallback search file path",
                condition=step.condition,
                on_failure=step.on_failure,
            )

        if "syntaxerror" in normalized_error and "with open" in content:
            fixed_content = content.replace("; with open", "\nwith open")
            return ActionStep(
                step_id=step.step_id,
                step_type=step.step_type,
                content=fixed_content,
                description_kr=f"{step.description_kr} (문법 보정)",
                expected_output=step.expected_output,
                condition=step.condition,
                on_failure=step.on_failure,
            )

        if "name 'len' is not defined" in normalized_error:
            return ActionStep(
                step_id=step.step_id,
                step_type=step.step_type,
                content=step.content,
                description_kr=f"{step.description_kr} (조건 재평가)",
                expected_output=step.expected_output,
                condition=step.condition,
                on_failure=step.on_failure,
            )

        return None

    def verify(self, goal: str, step_results: list) -> dict:
        """실행 결과가 목표를 달성했는지 검증 (planner_model 사용)"""
        lines = []
        for i, r in enumerate(step_results):
            status = "성공" if r.success else "실패"
            out = r.output[:150] if r.output else (r.error[:150] if r.error else "없음")
            lines.append(f"  단계 {i+1} [{status}]: {out}")
        results_summary = "\n".join(lines)
        prompt = _VERIFY_PROMPT.format(goal=goal, results_summary=results_summary)
        raw = self._call_llm(prompt, model=self.llm.planner_model,
                             client_override=self.llm.planner_client,
                             provider_override=self.llm.planner_provider,
                             role_hint="planner")
        self._write_trace("verify", goal, raw)
        data = self._parse_object(raw)
        return data if data else {"achieved": False, "summary_kr": "검증 실패"}

    # ── 내부 ──────────────────────────────────────────────────────────────────

    def _get_strategy_context(self, goal: str) -> str:
        """전략 기억에서 유사 과거 경험 조회 (실패 무시)"""
        try:
            from agent.strategy_memory import get_strategy_memory
            return get_strategy_memory().get_relevant_context(goal)
        except Exception:
            try:
                from agent.strategy_memory import get_strategy_memory
                return get_strategy_memory().get_relevant_context(goal)
            except Exception:
                return ""

    def _get_failure_hints(self, goal: str) -> str:
        """최근 실패 패턴 요약 문자열 반환"""
        try:
            from agent.strategy_memory import get_strategy_memory
            failures = get_strategy_memory().recent_failures(goal)
            return "\n".join(f"- {f}" for f in failures) if failures else ""
        except Exception:
            try:
                from agent.strategy_memory import get_strategy_memory
                failures = get_strategy_memory().recent_failures(goal)
                return "\n".join(f"- {f}" for f in failures) if failures else ""
            except Exception:
                return ""

    def _call_llm(self, prompt: str, model: str = "", client_override=None, provider_override: str = "", role_hint: str = "planner") -> str:
        """대화 히스토리와 독립적으로 LLM 호출. model이 없으면 planner_model 사용."""
        candidates = self._get_llm_candidates(role_hint, model, client_override, provider_override)
        if not candidates:
            return ""
        collected_parts: List[str] = []
        continuation_budget = 2
        active_prompt = prompt

        for candidate_index, (client, provider, target_model) in enumerate(candidates):
            while True:
                text = ""
                finish_reason = ""
                failed = False
                for attempt in range(3):
                    try:
                        if provider == "anthropic":
                            resp = client.messages.create(
                                model=target_model,
                                max_tokens=1000,
                                system=_SYS_JSON_ONLY,
                                messages=[{"role": "user", "content": active_prompt}],
                            )
                            text = " ".join(b.text for b in resp.content if b.type == "text")
                            finish_reason = str(getattr(resp, "stop_reason", "") or "")
                        else:
                            resp = client.chat.completions.create(
                                model=target_model,
                                messages=[
                                    {"role": "system", "content": _SYS_JSON_ONLY},
                                    {"role": "user", "content": active_prompt},
                                ],
                                temperature=0.1,
                                max_tokens=1000,
                            )
                            choice = resp.choices[0]
                            text = choice.message.content or ""
                            finish_reason = str(getattr(choice, "finish_reason", "") or "")
                        break
                    except Exception as e:
                        has_fallback = candidate_index < len(candidates) - 1
                        delay = self._extract_retry_delay_seconds(e, attempt) if self._is_retryable_llm_error(e) else 0.0
                        if has_fallback and delay >= 8.0:
                            next_model = candidates[candidate_index + 1][2]
                            logging.warning(
                                f"[Planner] {target_model} 장기 대기 오류({delay:.1f}s) → 선택된 대체 모델 {next_model}로 즉시 전환: {e}"
                            )
                            failed = True
                            break
                        if attempt < 2 and self._is_retryable_llm_error(e):
                            logging.warning(f"[Planner] LLM 일시 오류 ({target_model}) → {delay:.1f}s 대기 후 재시도: {e}")
                            time.sleep(delay)
                            continue
                        if has_fallback and self._is_retryable_llm_error(e):
                            next_model = candidates[candidate_index + 1][2]
                            logging.warning(f"[Planner] {target_model} 호출 실패 → 선택된 대체 모델 {next_model}로 전환: {e}")
                            failed = True
                            break
                        logging.error(f"[Planner] LLM 호출 오류 ({target_model}): {e}")
                        return "".join(collected_parts).strip()
                if failed:
                    break

                collected_parts.append(text)
                combined = "".join(collected_parts).strip()
                if continuation_budget <= 0 or not self._should_continue_llm_output(finish_reason, combined):
                    return combined

                continuation_budget -= 1
                active_prompt = (
                    "이전 JSON 응답이 길이 제한으로 잘렸습니다. 이미 출력한 텍스트는 반복하지 말고, "
                    "바로 이어지는 JSON 내용만 이어서 출력하세요.\n\n"
                    f"원래 요청:\n{prompt}\n\n"
                    f"지금까지 출력한 응답:\n{combined[-3000:]}"
                )
                logging.info("[Planner] LLM 응답이 잘려 이어받기를 시도합니다.")
                time.sleep(0.5)
        return "".join(collected_parts).strip()

    def _get_llm_candidates(self, role_hint: str, model: str, client_override, provider_override: str) -> List[tuple]:
        candidates: List[tuple] = []
        primary_model = model or getattr(self.llm, f"{role_hint}_model", "") or self.llm.model
        primary_provider = provider_override or getattr(self.llm, f"{role_hint}_provider", "") or self.llm.provider
        if client_override is not None:
            primary_client = client_override
        elif hasattr(self.llm, "get_role_fallback_targets"):
            primary_client = None
        else:
            primary_client = getattr(self.llm, f"{role_hint}_client", None) or getattr(self.llm, "client", None)

        seen = set()
        if primary_client and primary_model:
            key = (str(primary_provider or ""), str(primary_model or ""))
            candidates.append((primary_client, primary_provider, primary_model))
            seen.add(key)

        if hasattr(self.llm, "get_role_fallback_targets"):
            for client, provider, target_model in self.llm.get_role_fallback_targets(role_hint):
                key = (str(provider or ""), str(target_model or ""))
                if not client or not target_model or key in seen:
                    continue
                candidates.append((client, provider, target_model))
                seen.add(key)
        elif not candidates and primary_client and primary_model:
            candidates.append((primary_client, primary_provider, primary_model))
        return candidates

    def _sanitize_developer_items(self, items: list, goal: str = "", context: Dict[str, str] = None) -> list:
        has_repo_context = bool(context and any(key.startswith("step_") for key in context))
        has_code_change = False
        has_validate_repo = False
        has_test_validation = False
        sanitized = []
        for item in items:
            if not isinstance(item, dict):
                continue
            content = str(item.get("content", "") or "")
            description = str(item.get("description_kr", "") or "")
            disallowed_reason = self._find_disallowed_developer_reason(content, goal=goal, context=context)
            if disallowed_reason:
                logging.warning(f"[Planner] 개발 계획 거부 ({disallowed_reason})")
                return []
            if not is_read_only_step_content(content, description):
                has_code_change = True
            if self._is_validate_repo_validation_step(content):
                has_validate_repo = True
            if self._is_test_validation_step(content):
                has_test_validation = True
            sanitized.append(item)
        if has_repo_context:
            if any(str(item.get("step_type", "") or "").lower() == "think" for item in sanitized):
                logging.warning("[Planner] 개발 계획 거부 (bootstrap 이후 think 단계 재등장)")
                return []
            if not has_code_change:
                logging.warning("[Planner] 개발 계획 거부 (실제 코드 변경 단계 없음)")
                return []
            if self._developer_goal_requests_validate_repo(goal) and not has_validate_repo:
                logging.warning("[Planner] 개발 계획 거부 (validate_repo 검증 단계 없음)")
                return []
            if self._developer_goal_requests_tests(goal) and not has_test_validation:
                logging.warning("[Planner] 개발 계획 거부 (영향 테스트 검증 단계 없음)")
                return []
        return sanitized

    def _find_disallowed_developer_reason(self, content: str, goal: str = "", context: Dict[str, str] = None) -> str:
        text = content or ""
        for pattern, reason in _DISALLOWED_DEVELOPER_PATTERNS:
            if pattern.search(text):
                return reason
        normalized = self._normalize_developer_path(text)
        if "&&" in text:
            return "shell chaining"
        if "py_compile" in normalized:
            return "py_compile-only validation"
        if "tests/" in normalized and "voicecommand/tests/" not in normalized and "voicecommand.tests." not in normalized:
            return "root tests path"
        if context and any(key.startswith("step_") for key in context):
            for pattern in _DEVELOPER_RESCAN_PATTERNS:
                if pattern.search(text):
                    return "repeat repo scan after bootstrap"
        for candidate in self.extract_developer_path_candidates(text):
            if not self.is_allowed_developer_path(candidate, goal=goal, context=context):
                return f"out-of-scope path reference: {candidate}"
        return ""

    def extract_developer_path_candidates(self, text: str) -> List[str]:
        normalized = self._normalize_developer_path(text)
        if not normalized:
            return []
        matches = []
        for candidate in _DEVELOPER_PATH_LITERAL_RE.findall(normalized):
            cleaned = self._normalize_developer_path(candidate)
            if cleaned:
                matches.append(cleaned)
        return list(dict.fromkeys(matches))

    def get_developer_allowed_prefixes(self, goal: str = "", context: Dict[str, str] = None) -> List[str]:
        prefixes = []

        def add(prefix: str) -> None:
            cleaned = self._normalize_developer_path(prefix)
            if cleaned and cleaned not in prefixes:
                prefixes.append(cleaned)

        normalized_goal = self._normalize_developer_path(goal)
        for scope in ("agent", "core", "ui", "plugins", "tests"):
            if f"voicecommand/{scope}" in normalized_goal:
                add(f"voicecommand/{scope}")
        if re.search(r"(?<!voicecommand/)\bdocs\b", normalized_goal):
            add("docs")

        if context:
            repo_scan = str(context.get("step_0_output", "") or "")
            try:
                payload = json.loads(repo_scan)
            except Exception:
                payload = {}
            if isinstance(payload, dict):
                for area in payload.keys():
                    lowered = str(area).strip().lower()
                    if lowered == "docs":
                        add("docs")
                    elif lowered in {"agent", "core", "ui", "plugins", "tests"}:
                        add(f"voicecommand/{lowered}")

        add("voicecommand/validate_repo.py")
        if not prefixes:
            for prefix in _DEFAULT_DEVELOPER_SCOPE_PREFIXES:
                add(prefix)
        return prefixes

    def is_allowed_developer_path(self, path: str, goal: str = "", context: Dict[str, str] = None) -> bool:
        normalized = self._normalize_developer_path(path)
        if not normalized:
            return True
        allowed_prefixes = self.get_developer_allowed_prefixes(goal=goal, context=context)
        for prefix in allowed_prefixes:
            if normalized == prefix or normalized.startswith(prefix + "/"):
                return True
        return False

    def _normalize_developer_path(self, text: str) -> str:
        value = str(text or "").strip().strip('"').strip("'")
        if not value:
            return ""
        return value.replace("\\\\", "/").replace("\\", "/").lstrip("./").lower()

    def _developer_goal_requests_validate_repo(self, goal: str) -> bool:
        normalized = self._normalize_developer_path(goal)
        return "validate_repo.py" in normalized or "--compile-only" in normalized or "검증" in (goal or "")

    def _developer_goal_requests_tests(self, goal: str) -> bool:
        return bool(re.search(r"(영향받는\s*테스트|관련\s*테스트|pytest|unittest|tests?)", goal or "", re.IGNORECASE))

    def _is_validate_repo_validation_step(self, content: str) -> bool:
        normalized = self._normalize_developer_path(content)
        return "validate_repo.py" in normalized

    def _is_test_validation_step(self, content: str) -> bool:
        normalized = self._normalize_developer_path(content)
        if "pytest" not in normalized and "unittest" not in normalized:
            return False
        if "tests/" in normalized and "voicecommand/tests/" not in normalized:
            return False
        return "voicecommand/tests/" in normalized or "voicecommand.tests." in normalized

    def _is_retryable_llm_error(self, error: Exception) -> bool:
        return bool(_LLM_RETRYABLE_ERROR_RE.search(str(error or "")))

    def _extract_retry_delay_seconds(self, error: Exception, attempt: int) -> float:
        text = str(error or "")
        for pattern in _LLM_RETRY_DELAY_RE_LIST:
            match = pattern.search(text)
            if match:
                try:
                    return max(0.5, min(float(match.group(1)), 60.0))
                except Exception:
                    continue
        return min(2.0 * (attempt + 1), 10.0)

    def _should_continue_llm_output(self, finish_reason: str, text: str) -> bool:
        normalized = (finish_reason or "").lower()
        if normalized in {"length", "max_tokens"}:
            return True
        if not text:
            return False
        stripped = text.strip()
        if stripped.startswith("[") and stripped.count("[") > stripped.count("]"):
            return True
        if stripped.startswith("{") and stripped.count("{") > stripped.count("}"):
            return True
        return False

    def _parse_array(self, text: str) -> list:
        text = _RE_CODE_FENCE.sub('', text.strip())
        candidate = self._extract_balanced(text, "[", "]")
        if candidate:
            try:
                return json.loads(candidate)
            except Exception:
                logging.warning(f"[Planner] JSON 배열 파싱 실패: {candidate[:200]}")
        recovered = self._recover_partial_array(text)
        if recovered:
            logging.info("[Planner] 부분 JSON 배열 복구 적용")
            return recovered
        return []

    def _parse_object(self, text: str) -> dict:
        text = _RE_CODE_FENCE.sub('', text.strip())
        candidate = self._extract_balanced(text, "{", "}")
        if candidate:
            try:
                return json.loads(candidate)
            except Exception:
                logging.warning(f"[Planner] JSON 객체 파싱 실패: {candidate[:200]}")
        recovered = self._recover_partial_object(text)
        if recovered:
            logging.info("[Planner] 부분 JSON 객체 복구 적용")
            return recovered
        return {}

    def _recover_partial_array(self, text: str) -> list:
        start = text.find("[")
        if start < 0:
            return []
        items = []
        cursor = start
        while cursor < len(text):
            obj_start = text.find("{", cursor)
            if obj_start < 0:
                break
            obj_text, obj_end = self._extract_partial_object(text, obj_start)
            if not obj_text:
                break
            try:
                items.append(json.loads(obj_text))
            except Exception:
                break
            cursor = obj_end
            comma_idx = text.find(",", cursor)
            if comma_idx < 0:
                break
            cursor = comma_idx + 1
        return items

    def _recover_partial_object(self, text: str) -> dict:
        obj_start = text.find("{")
        if obj_start < 0:
            return {}
        obj_text, _ = self._extract_partial_object(text, obj_start)
        if not obj_text:
            return {}
        try:
            return json.loads(obj_text)
        except Exception:
            return {}

    def _extract_partial_object(self, text: str, start: int) -> tuple[str, int]:
        depth = 0
        in_string = False
        escape = False
        for idx in range(start, len(text)):
            ch = text[idx]
            if in_string:
                if escape:
                    escape = False
                elif ch == "\\":
                    escape = True
                elif ch == '"':
                    in_string = False
                continue
            if ch == '"':
                in_string = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return text[start:idx + 1], idx + 1
        return "", start

    def _extract_balanced(self, text: str, open_char: str, close_char: str) -> str:
        start = text.find(open_char)
        if start < 0:
            return ""
        depth = 0
        in_string = False
        escape = False
        for idx in range(start, len(text)):
            ch = text[idx]
            if in_string:
                if escape:
                    escape = False
                elif ch == "\\":
                    escape = True
                elif ch == '"':
                    in_string = False
                continue
            if ch == '"':
                in_string = True
            elif ch == open_char:
                depth += 1
            elif ch == close_char:
                depth -= 1
                if depth == 0:
                    return text[start:idx + 1]
        return ""

    def _fmt_context(self, context: Dict[str, str]) -> str:
        if not context:
            return ""
        lines = ["이전 단계 결과:"]
        for k, v in context.items():
            lines.append(f"  {k}: {str(v)[:120]}")
        return "\n".join(lines) + "\n"

    def _fmt_developer_context(self, context: Dict[str, str]) -> str:
        if not context:
            return ""
        lines = ["저장소 개발 컨텍스트:"]

        repo_scan = str(context.get("step_0_output", "") or "")
        if repo_scan:
            try:
                data = json.loads(repo_scan)
                for area, info in data.items():
                    file_count = info.get("file_count", 0)
                    samples = ", ".join((info.get("samples") or [])[:3])
                    lines.append(f"  {area}: file_count={file_count}, samples={samples}")
            except Exception:
                lines.append(f"  repo_scan: {repo_scan[:180]}")

        validate_preview = str(context.get("step_1_output", "") or "")
        if validate_preview:
            compile_targets = len(re.findall(r'^\s*\"?[A-Za-z0-9_/.-]+\.py\"?,?$', validate_preview, flags=re.MULTILINE))
            has_compile_only = "--compile-only" in validate_preview
            lines.append(f"  validate_repo: compile_targets~{compile_targets}, compile_only={has_compile_only}")

        tests_output = str(context.get("step_2_output", "") or "")
        if tests_output:
            try:
                test_names = json.loads(tests_output)
                if isinstance(test_names, list):
                    lines.append(f"  tests: count={len(test_names)}, samples={', '.join(test_names[:5])}")
                else:
                    lines.append(f"  tests: {tests_output[:180]}")
            except Exception:
                lines.append(f"  tests: {tests_output[:180]}")

        previous_attempt = str(context.get("이전_시도", "") or "")
        if previous_attempt:
            lines.append(f"  previous_attempt: {previous_attempt[:200]}")

        recent_episodes = str(context.get("recent_goal_episodes", "") or "")
        if recent_episodes:
            compact = " ".join(line.strip() for line in recent_episodes.splitlines()[:3] if line.strip())
            lines.append(f"  recent_goal_episodes: {compact[:220]}")

        return "\n".join(lines) + "\n"

    def _write_trace(self, stage: str, goal: str, raw: str):
        try:
            from core.resource_manager import ResourceManager
            log_dir = ResourceManager.get_writable_path("logs")
            os.makedirs(log_dir, exist_ok=True)
            path = os.path.join(log_dir, f"planner_trace_{datetime.now().strftime('%Y%m%d')}.log")
            with open(path, "a", encoding="utf-8") as f:
                f.write(
                    f"[{datetime.now().strftime('%H:%M:%S')}] {stage}\n"
                    f"goal: {goal}\n"
                    f"raw:\n{raw[:4000]}\n"
                    f"{'=' * 80}\n"
                )
        except Exception as e:
            logging.warning(f"[Planner] trace 저장 실패: {e}")


# ── 싱글톤 ─────────────────────────────────────────────────────────────────────

_planner: Optional[AgentPlanner] = None


def get_planner() -> AgentPlanner:
    global _planner
    if _planner is None:
        try:
            from agent.llm_provider import get_llm_provider
        except Exception:
            from agent.llm_provider import get_llm_provider
        _planner = AgentPlanner(get_llm_provider())
    return _planner
