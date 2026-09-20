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


