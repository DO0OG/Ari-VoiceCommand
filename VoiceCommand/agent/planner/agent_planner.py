"""
AgentPlanner — 목표 분해 / 단계 수정 / 결과 검증 플래너 핵심 로직.
"""
import json
import logging
import os
import re
import threading
import time
from datetime import datetime
from typing import List, Optional, Dict

from agent.execution_analysis import is_read_only_step_content
from agent.planner_json_utils import (
    extract_balanced,
    extract_partial_object,
    parse_json_array,
    parse_json_object,
    recover_partial_array,
    recover_partial_object,
)
from agent.planner.action_step import ActionStep
from agent.planner.template_plans import TemplatePlansMixin

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
  "summary": "달성 여부 한국어 요약 (1~2문장)"
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

_DECOMPOSE_PROMPT_EN = """\
Return an execution plan as a JSON array to achieve the following goal.

Goal: {goal}
{context_block}
Rules:
- step_type: "python" (Python code), "shell" (CMD/PowerShell), "think" (analysis, no content)
- Simple tasks need only one step
- Write immediately executable code
- Use multi-line code for compound statements (with/for/if/try), not semicolons
- Previous step outputs are available as step_outputs dict (keys: "step_0_output", etc.)
- Set condition for steps that depend on previous results
- on_failure: "abort", "skip", or "continue"
- Windows desktop path: use 'desktop_path' variable directly in Python code
- Always ensure directories exist: os.makedirs(path, exist_ok=True)
- Use web_search(query) and web_fetch(url) instead of external APIs
- Use save_document(directory, base_name, content) for saving documents
- No YOUR_API_KEY or paid external API dependencies
- Return JSON array only

Output format:
[
  {{
    "step_type": "python",
    "content": "code to execute",
    "description_kr": "step description",
    "expected_output": "expected result",
    "condition": "",
    "on_failure": "abort"
  }}
]"""

_DEVELOPER_DECOMPOSE_PROMPT_EN = """\
Return an execution plan as a JSON array to achieve the following repository development goal.

Goal: {goal}
{context_block}
Rules:
- step_type: "python", "shell", or "think" only
- Return at most 4 steps
- shell steps use PowerShell commands
- shell commands assume repo root as working directory
- python steps can use repo_root and module_dir variables directly
- Keep content short and executable; do not paste entire file contents
- Previous step outputs available as step_outputs dict
- If no scan results yet, focus on information gathering only
- If scan results available, select one improvement task and modify one file at a time
- Limit target to VoiceCommand/agent, core, ui, plugins, tests, docs, validate_repo.py
- Use repo_root and module_dir for paths, do not hardcode
- Validation step must include: py -3.11 VoiceCommand\\validate_repo.py --compile-only
- No py_compile, no tests/ root path, no && chaining
- Return JSON array only

Output format:
[
  {{
    "step_type": "shell",
    "content": "PowerShell command",
    "description_kr": "step description",
    "expected_output": "expected result",
    "condition": "",
    "on_failure": "abort"
  }}
]
"""

_DEVELOPER_RETRY_PROMPT_EN = """\
Repository scan is complete. Return a 2-step plan as a JSON array to modify actual code.

Goal: {goal}
{context_block}
Rules:
- Do NOT include any scan/listing steps. They are already done.
- Return exactly 2 steps: [code_edit, validation]
- code_edit step: select one actual file from context and modify it using open(path,'w') or path.write_text()
  Write real Python/shell code. No placeholders like print('edit one file').
- Target files must be within: VoiceCommand/agent, core, ui, plugins, tests, docs
- Validation step must include: py -3.11 VoiceCommand\\validate_repo.py --compile-only
- No py_compile, no tests/ root path, no &&, no full repo re-scan
- step_type: "python" or "shell" only
- python steps can use repo_root, module_dir, step_outputs directly
- content must be executable code, max 6 lines
- Return JSON array only

Bad example (forbidden):
[{{"step_type":"python","content":"print('edit one file')","description_kr":"file edit"}}]

Good example:
[
  {{"step_type":"python","content":"import os\\npath = os.path.join(repo_root,'VoiceCommand','agent','skill_library.py')\\ntext = open(path,'r',encoding='utf-8').read()\\ntext = text.replace('old_pattern','new_pattern',1)\\nopen(path,'w',encoding='utf-8').write(text)\\nprint('done')", "description_kr":"Modify skill_library.py pattern","expected_output":"done"}},
  {{"step_type":"shell","content":"py -3.11 VoiceCommand\\\\validate_repo.py --compile-only; py -3.11 -m unittest VoiceCommand.tests.test_skill_library","description_kr":"Validate and run affected tests","expected_output":"compile-only checks passed"}}
]
"""

_FIX_PROMPT_EN = """\
The following code/command failed with an error. Return the fixed version as JSON.

Original code:
{content}

Error message:
{error}

Goal: {goal}
{context_block}
Fix guidelines:
- Analyze the root cause and fix it fundamentally
- Do not retry the same approach
- Windows desktop path: use 'desktop_path' variable directly in Python code
- For repo/code tasks, use repo_root and module_dir; do not guess Desktop path
- Do not hardcode paths or executable locations; use runtime discovery or provided helpers
- Use web_search / web_fetch for web access; no YOUR_API_KEY placeholders
- Use save_document(...) helper for saving documents when possible
- Use compound statements (with/for/if/try) on multiple lines, not semicolons
- Return JSON object only

Output format:
{{
  "step_type": "python",
  "content": "fixed code",
  "description_kr": "reason for fix",
  "expected_output": "expected result"
}}"""

_VERIFY_PROMPT_EN = """\
Evaluate whether the following execution results achieved the goal.

Goal: {goal}

Execution results:
{results_summary}

Criteria:
- For system state changes (file/folder creation), set achieved=true only when outputs contain no errors
- If any step output contains error messages, exceptions, or "failed", set achieved=false
- When uncertain, set achieved=false

Return JSON object only:
{{
  "achieved": true,
  "summary": "1-2 sentence summary of whether goal was achieved"
}}"""

_REFLECT_PROMPT_EN = """\
The agent ultimately failed to achieve the goal. Analyze the failure and write a 'lesson' for the next attempt as JSON.

Goal: {goal}

Execution history summary:
{history_summary}

Writing rules:
- Describe the root cause of failure (e.g., missing library, permission issue, logic error)
- Specify approaches that must be avoided in the next attempt
- Summarize the recommended alternative approach in one sentence
- Return JSON object only

Output format:
{{
  "reason": "root cause of failure",
  "avoid": "what to avoid",
  "lesson": "key lesson for the next attempt"
}}"""


def _get_lang() -> str:
    try:
        from i18n.translator import get_language
        return get_language()
    except Exception as exc:
        logging.debug("[Planner] 언어 설정 조회 실패, ko 기본값 사용: %s", exc)
        return "ko"


def _get_decompose_prompt() -> str:
    return _DECOMPOSE_PROMPT_EN if _get_lang() != "ko" else _DECOMPOSE_PROMPT


def _get_developer_decompose_prompt() -> str:
    return _DEVELOPER_DECOMPOSE_PROMPT_EN if _get_lang() != "ko" else _DEVELOPER_DECOMPOSE_PROMPT


def _get_developer_retry_prompt() -> str:
    return _DEVELOPER_RETRY_PROMPT_EN if _get_lang() != "ko" else _DEVELOPER_RETRY_PROMPT


def _get_fix_prompt() -> str:
    return _FIX_PROMPT_EN if _get_lang() != "ko" else _FIX_PROMPT


def _get_verify_prompt() -> str:
    return _VERIFY_PROMPT_EN if _get_lang() != "ko" else _VERIFY_PROMPT


def _get_reflect_prompt() -> str:
    return _REFLECT_PROMPT_EN if _get_lang() != "ko" else _REFLECT_PROMPT


class AgentPlanner(TemplatePlansMixin):
    """목표 분해 / 단계 수정 / 결과 검증 플래너"""

    def __init__(self, llm_provider):
        self.llm = llm_provider
        self._last_learning_signals: Dict[str, bool] = {}

    def reflect(self, goal: str, history_summary: str) -> Dict[str, str]:
        """실패 원인 분석 및 교훈 도출 (planner_model 사용)"""
        prompt = _get_reflect_prompt().format(goal=goal, history_summary=history_summary)
        try:
            resp = self._call_llm(prompt, model=self.llm.planner_model,
                                  client_override=self.llm.planner_client,
                                  provider_override=self.llm.planner_provider,
                                  role_hint="planner")
            return self._parse_object(resp) or {}
        except Exception as e:
            logging.error("[Planner] 반성 실패: %s", e)
            return {}

    # ── 공개 API ──────────────────────────────────────────────────────────────

    def decompose(self, goal: str, context: Dict[str, str] = None) -> List[ActionStep]:
        """목표를 실행 단계 목록으로 분해 (planner_model 사용)"""
        from agent.dag_builder import extract_resources, build_dag, assign_parallel_groups, annotate_steps
        from agent.few_shot_injector import get_few_shot_injector
        from agent.planner_feedback import get_planner_feedback_loop
        signals = {
            "StrategyMemory": False,
            "EpisodeMemory": False,
            "FewShot": False,
            "PlannerFeedback": False,
        }

        def _annotate(steps: List[ActionStep]) -> List[ActionStep]:
            for step in steps:
                step.reads, step.writes = extract_resources(step.content, step.step_type)
            dag = build_dag(steps)
            groups = assign_parallel_groups(dag)
            return annotate_steps(steps, dag, groups)

        templated = self._build_template_plan(goal)
        if templated:
            logging.info("[Planner] 템플릿 계획 사용: %s", goal)
            self._last_learning_signals = signals
            return _annotate(templated)

        is_dev_goal = self.is_developer_goal(goal)

        # 과거 전략 기억 주입
        if is_dev_goal:
            ctx_block = self._fmt_developer_context(context, goal=goal)
            failure_hints = self._get_failure_hints(goal)
            if failure_hints:
                signals["StrategyMemory"] = True
                ctx_block = "## 최근 실패 힌트\n" + failure_hints + "\n" + ctx_block
        else:
            feedback_loop = get_planner_feedback_loop()
            feedback_tags = feedback_loop.infer_tags(goal=goal)
            strategy_ctx = ""
            try:
                from agent.learning_metrics import get_learning_metrics

                metrics = get_learning_metrics()
                should_activate = getattr(metrics, "should_activate", lambda *args, **kwargs: True)
                if should_activate("StrategyMemory"):
                    strategy_ctx = self._get_strategy_context(goal)
            except Exception:
                strategy_ctx = self._get_strategy_context(goal)
            episode_failure_patterns = self._get_episode_failure_patterns(goal)
            ctx_block = self._fmt_context(context)
            if strategy_ctx:
                signals["StrategyMemory"] = True
                ctx_block = strategy_ctx + "\n" + ctx_block
            if episode_failure_patterns:
                signals["EpisodeMemory"] = True
                ctx_block = "## 반복 실패 패턴\n" + episode_failure_patterns + "\n" + ctx_block
            few_shot = get_few_shot_injector().get_examples(goal)
            if few_shot:
                signals["FewShot"] = True
                ctx_block = few_shot + "\n" + ctx_block
            feedback_hints = feedback_loop.get_hints(goal, feedback_tags)
            if feedback_hints:
                signals["PlannerFeedback"] = True
                ctx_block = feedback_hints + "\n" + ctx_block

        prompt_template = _get_developer_decompose_prompt() if is_dev_goal else _get_decompose_prompt()
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
                    self._last_learning_signals = signals
                    return _annotate(fallback_steps)
        if not items:
            logging.warning("[Planner] decompose 파싱 실패: %s", raw[:200])
            self._last_learning_signals = signals
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
                optional=bool(s.get("optional", False)),
            )
            for i, s in enumerate(items)
        ]
        self._last_learning_signals = signals
        return _annotate(steps)

    def get_last_learning_signals(self) -> Dict[str, bool]:
        return dict(self._last_learning_signals)

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
        retry_ctx = self._fmt_developer_context(context, goal=goal)
        retry_prompt = _get_developer_retry_prompt().format(goal=goal, context_block=retry_ctx)
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
        """개발자 모드 초기화 플랜 생성 — 저장소 스캔·검증 스크립트 확인·테스트 목록 수집."""
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
                    "    summary[label] = {'file_count': len(files), 'samples': files[:5]}\n"
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
                    "    and name.startswith('test_') and name.endswith('.py')\n"
                    "]\n"
                    "print(json.dumps(names, ensure_ascii=False))"
                ),
                description_kr="관련 테스트 목록 수집",
                expected_output="test file list",
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

        prompt = _get_fix_prompt().format(
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
            logging.warning("[Planner] fix_step 파싱 실패: %s", raw[:200])
            heuristic = self._heuristic_fix_step(step, error, goal, context)
            if heuristic:
                return heuristic
            return None
        if self.is_developer_goal(goal):
            disallowed_reason = self._find_disallowed_developer_reason(data.get("content", ""), goal=goal, context=context)
            if disallowed_reason:
                logging.warning("[Planner] 개발용 수정안 거부 (%s)", disallowed_reason)
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
            optional=step.optional,
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
                optional=step.optional,
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
                optional=step.optional,
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
                optional=step.optional,
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
        prompt = _get_verify_prompt().format(goal=goal, results_summary=results_summary)
        raw = self._call_llm(prompt, model=self.llm.planner_model,
                             client_override=self.llm.planner_client,
                             provider_override=self.llm.planner_provider,
                             role_hint="planner")
        self._write_trace("verify", goal, raw)
        data = self._parse_object(raw)
        return data if data else {"achieved": False, "summary": "검증 실패"}

    # ── 내부 ──────────────────────────────────────────────────────────────────

    def _with_strategy_memory(self, callback, default):
        try:
            from agent.strategy_memory import get_strategy_memory
            return callback(get_strategy_memory())
        except Exception as exc:
            logging.debug("[Planner] StrategyMemory 접근 실패, 기본값 사용: %s", exc)
            return default

    def _with_episode_memory(self, callback, default):
        try:
            from agent.episode_memory import get_episode_memory
            return callback(get_episode_memory())
        except Exception as exc:
            logging.debug("[Planner] EpisodeMemory 접근 실패, 기본값 사용: %s", exc)
            return default

    def _get_strategy_context(self, goal: str) -> str:
        """전략 기억에서 유사 과거 경험 조회 (실패 무시)"""
        return self._with_strategy_memory(
            lambda memory: memory.get_relevant_context(goal),
            "",
        )

    def _get_failure_hints(self, goal: str) -> str:
        """최근 실패 패턴 요약 문자열 반환"""
        return self._with_strategy_memory(
            lambda memory: self._format_failure_items(memory.recent_failures(goal)),
            "",
        )

    def _get_episode_failure_patterns(self, goal: str) -> str:
        return self._with_episode_memory(
            lambda memory: self._format_failure_items(memory.get_failure_patterns(goal, limit=3)),
            "",
        )

    def _format_failure_items(self, items) -> str:
        return "\n".join(f"- {item}" for item in items) if items else ""

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
                            extra_kwargs = {}
                            if self._supports_json_response_format(provider):
                                extra_kwargs["response_format"] = {"type": "json_object"}
                            resp = client.chat.completions.create(
                                model=target_model,
                                messages=[
                                    {"role": "system", "content": _SYS_JSON_ONLY},
                                    {"role": "user", "content": active_prompt},
                                ],
                                temperature=0.1,
                                max_tokens=1000,
                                **extra_kwargs,
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
                                "[Planner] %s 장기 대기 오류(%.1fs) → 선택된 대체 모델 %s로 즉시 전환: %s",
                                target_model,
                                delay,
                                next_model,
                                e,
                            )
                            failed = True
                            break
                        if attempt < 2 and self._is_retryable_llm_error(e):
                            logging.warning(
                                "[Planner] LLM 일시 오류 (%s) → %.1fs 대기 후 재시도: %s",
                                target_model,
                                delay,
                                e,
                            )
                            time.sleep(delay)
                            continue
                        if has_fallback and self._is_retryable_llm_error(e):
                            next_model = candidates[candidate_index + 1][2]
                            logging.warning(
                                "[Planner] %s 호출 실패 → 선택된 대체 모델 %s로 전환: %s",
                                target_model,
                                next_model,
                                e,
                            )
                            failed = True
                            break
                        logging.error("[Planner] LLM 호출 오류 (%s): %s", target_model, e)
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

    @staticmethod
    def _supports_json_response_format(provider: str) -> bool:
        return str(provider or "").strip().lower() in {"openai", "groq"}

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
                logging.warning("[Planner] 개발 계획 거부 (%s)", disallowed_reason)
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
            except Exception as exc:
                logging.debug("[Planner] repo_scan JSON 파싱 실패, 빈 payload 사용: %s", exc)
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
                except Exception as exc:
                    logging.debug("[Planner] 재시도 지연 파싱 실패, 다음 패턴 확인: %s", exc)
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
        return parse_json_array(text)

    def _parse_object(self, text: str) -> dict:
        return parse_json_object(text)

    def _recover_partial_array(self, text: str) -> list:
        return recover_partial_array(text)

    def _recover_partial_object(self, text: str) -> dict:
        return recover_partial_object(text)

    def _extract_partial_object(self, text: str, start: int) -> tuple[str, int]:
        return extract_partial_object(text, start)

    def _extract_balanced(self, text: str, open_char: str, close_char: str) -> str:
        return extract_balanced(text, open_char, close_char)

    def _fmt_context(self, context: Dict[str, str]) -> str:
        if not context:
            return ""
        lines = ["이전 단계 결과:"]
        for k, v in context.items():
            lines.append(f"  {k}: {str(v)[:120]}")
        return "\n".join(lines) + "\n"

    @staticmethod
    def _infer_relevant_tests(test_names: list, goal: str) -> list:
        """goal에서 대상 .py 파일명을 추출해 관련 테스트 파일을 선별."""
        if not test_names or not goal:
            return []
        py_refs = re.findall(r'\b(\w+)\.py\b', goal.lower())
        target_bases = {name.removeprefix("test_") for name in py_refs if name}
        if not target_bases:
            return []
        relevant = []
        for test_name in test_names:
            base = test_name.lower().removeprefix("test_").removesuffix(".py")
            if any(base in tb or tb in base for tb in target_bases if len(tb) > 3):
                relevant.append(test_name)
        return relevant

    def _fmt_developer_context(self, context: Dict[str, str], goal: str = "") -> str:
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
            except Exception as exc:
                logging.debug("[Planner] 개발 컨텍스트 repo_scan 해석 실패: %s", exc)
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
                    relevant = self._infer_relevant_tests(test_names, goal)
                    if relevant:
                        lines.append(
                            f"  tests: count={len(test_names)}, "
                            f"relevant={', '.join(relevant)}, "
                            f"all={', '.join(test_names)}"
                        )
                    else:
                        lines.append(f"  tests: count={len(test_names)}, all={', '.join(test_names)}")
                else:
                    lines.append(f"  tests: {tests_output[:180]}")
            except Exception as exc:
                logging.debug("[Planner] 개발 컨텍스트 tests 해석 실패: %s", exc)
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
            logging.warning("[Planner] trace 저장 실패: %s", e)


# ── 싱글톤 ─────────────────────────────────────────────────────────────────────

_planner: Optional[AgentPlanner] = None
_planner_lock = threading.Lock()


def get_planner() -> AgentPlanner:
    global _planner
    if _planner is None:
        with _planner_lock:
            if _planner is None:
                from agent.llm_provider import get_llm_provider
                _planner = AgentPlanner(get_llm_provider())
    return _planner
