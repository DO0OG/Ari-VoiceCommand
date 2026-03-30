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
from datetime import datetime
from dataclasses import dataclass, field
from typing import List, Optional, Dict

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
- GUI/브라우저 자동화에는 `open_url`, `open_path`, `launch_app`, `wait_seconds`, `click_screen`, `click_image`, `is_image_visible`, `move_mouse`, `type_text`, `press_keys`, `hotkey`, `take_screenshot`, `read_clipboard`, `write_clipboard`, `wait_for_window`, `get_active_window_title`, `list_open_windows`, `get_desktop_state`, `browser_login`, `run_browser_actions`, `run_adaptive_browser_workflow`, `run_resilient_browser_workflow`, `run_desktop_workflow`, `run_adaptive_desktop_workflow`, `run_resilient_desktop_workflow`, `get_runtime_state`, `get_learned_strategies`, `get_planning_snapshot` 헬퍼를 사용할 수 있습니다.
- 브라우저 액션 타입으로 `wait_url`, `wait_title`, `wait_selector`, `read_title`, `read_url`, `read_links`, `download_wait`를 사용할 수 있습니다.
- 반복 GUI/브라우저 작업 전에는 `get_planning_snapshot_summary(goal_hint='...')` 또는 `get_planning_snapshot(goal_hint='...')`로 현재 상태 + 과거 성공 전략을 먼저 읽고, 가능한 경우 `run_resilient_browser_workflow(...)` / `run_resilient_desktop_workflow(...)`를 우선 사용하세요.
- `run_browser_actions(url, actions, goal_hint='로그인 후 다운로드')`처럼 `goal_hint`를 함께 주면 이전 성공 액션 시퀀스를 재사용할 수 있습니다.
- `run_desktop_workflow(goal_hint='메모장에 메모 저장', app_target='notepad', expected_window='메모장', actions=[...])`처럼 사용하면 창 전략과 후속 액션을 함께 재사용할 수 있습니다.
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
- 웹 검색이 필요하면 `web_search` / `web_fetch`를 사용하고, `YOUR_API_KEY` 같은 자리표시자는 절대 사용하지 마세요.
- 문서 저장은 가능하면 `save_document(...)` 도우미를 사용하세요.
- 파일 작업은 가능하면 `rename_file`, `merge_files`, `organize_folder`, `analyze_data`, `generate_report`, `detect_file_set`, `batch_rename_files` 도우미를 사용하세요.
- GUI/브라우저 자동화가 필요하면 가능한 한 내장 헬퍼(`open_url`, `launch_app`, `click_screen`, `type_text`, `wait_for_window`, `list_open_windows`, `get_desktop_state`, `browser_login`, `run_browser_actions`, `run_adaptive_browser_workflow`, `run_resilient_browser_workflow`, `run_desktop_workflow`, `run_adaptive_desktop_workflow`, `run_resilient_desktop_workflow`, `get_runtime_state`, `get_learned_strategies`, `get_planning_snapshot` 등)를 사용하세요.
- 브라우저에서 리다이렉트/동적 로딩이 예상되면 `wait_url`, `wait_title`, `wait_selector` 같은 액션을 포함하세요.
- 이미 비슷한 전략이 있다면 `get_planning_snapshot_summary(goal_hint=...)`를 우선 참고하고, 필요할 때만 전체 `get_planning_snapshot(...)` 또는 `get_learned_strategies(...)`를 읽으세요.
- 브라우저 작업은 가능하면 `goal_hint`를 명시해 재사용 가능한 액션 전략을 남기세요.
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
                                  provider_override=self.llm.planner_provider)
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

        # 과거 전략 기억 주입
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

        prompt = _DECOMPOSE_PROMPT.format(goal=goal, context_block=ctx_block)
        raw = self._call_llm(prompt, model=self.llm.planner_model,
                             client_override=self.llm.planner_client,
                             provider_override=self.llm.planner_provider)
        self._write_trace("decompose", goal, raw)
        items = self._parse_array(raw)
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

    def _build_template_plan(self, goal: str) -> List[ActionStep]:
        """LLM이 자주 실패하는 검색-요약-저장 계열 작업은 안정적인 템플릿으로 우선 처리."""
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

        if profile.wants_organize and (profile.source_path or profile.wants_desktop):
            return self._build_organize_folder_plan(profile)

        if profile.wants_log_report and profile.source_path:
            return self._build_log_report_plan(profile)

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
        folder_name_match = re.search(r'([가-힣A-Za-z0-9._-]+)\s*폴더', normalized)
        if "뉴스" in normalized:
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
            wants_analyze=any(token in normalized for token in ("분석", "통계", "구조 확인", "요약")),
            wants_log_report="로그" in normalized and any(token in normalized for token in ("리포트", "보고", "분석", "요약")),
            wants_security_audit=any(
                token in normalized
                for token in ("보안 점검", "자체 보안 점검", "보안 검사", "보안 진단", "security check", "security audit")
            ),
            wants_type_text=any(token in normalized for token in ("입력", "적어", "써", "작성", "type")),
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
                             provider_override=self.llm.execution_provider)
        self._write_trace("fix_step", goal, raw)
        data = self._parse_object(raw)
        if not data or not data.get("content"):
            logging.warning(f"[Planner] fix_step 파싱 실패: {raw[:200]}")
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
                             provider_override=self.llm.planner_provider)
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

    def _call_llm(self, prompt: str, model: str = "", client_override=None, provider_override: str = "") -> str:
        """대화 히스토리와 독립적으로 LLM 호출. model이 없으면 planner_model 사용."""
        target_model = model or self.llm.planner_model
        client = client_override if client_override is not None else self.llm.client
        provider = provider_override or self.llm.provider
        try:
            if not client:
                return ""
            if provider == "anthropic":
                resp = client.messages.create(
                    model=target_model,
                    max_tokens=1000,
                    system=_SYS_JSON_ONLY,
                    messages=[{"role": "user", "content": prompt}],
                )
                return " ".join(b.text for b in resp.content if b.type == "text")
            else:
                resp = client.chat.completions.create(
                    model=target_model,
                    messages=[
                        {"role": "system", "content": _SYS_JSON_ONLY},
                        {"role": "user", "content": prompt},
                    ],
                    temperature=0.1,
                    max_tokens=1000,
                )
                return resp.choices[0].message.content or ""
        except Exception as e:
            logging.error(f"[Planner] LLM 호출 오류 ({target_model}): {e}")
            return ""

    def _parse_array(self, text: str) -> list:
        text = _RE_CODE_FENCE.sub('', text.strip())
        candidate = self._extract_balanced(text, "[", "]")
        if candidate:
            try:
                return json.loads(candidate)
            except Exception:
                logging.warning(f"[Planner] JSON 배열 파싱 실패: {candidate[:200]}")
        return []

    def _parse_object(self, text: str) -> dict:
        text = _RE_CODE_FENCE.sub('', text.strip())
        candidate = self._extract_balanced(text, "{", "}")
        if candidate:
            try:
                return json.loads(candidate)
            except Exception:
                logging.warning(f"[Planner] JSON 객체 파싱 실패: {candidate[:200]}")
        return {}

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
