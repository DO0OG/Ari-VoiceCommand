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
from dataclasses import dataclass
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


@dataclass
class ActionStep:
    step_id: int
    step_type: str        # "python" | "shell" | "think"
    content: str          # 실행할 코드 또는 명령 (think는 빈 문자열 가능)
    description_kr: str
    expected_output: str = ""
    condition: str = ""        # Python 표현식. 비어있으면 항상 실행.
    on_failure: str = "abort"  # "abort"(중단) | "skip"(건너뜀) | "continue"(계속)


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
    source_path: str = ""
    destination_path: str = ""
    url: str = ""
    target_name: str = "result"
    preferred_format: str = "auto"


_SYS_JSON_ONLY = "당신은 JSON만 반환하는 전문가입니다. 설명 없이 순수 JSON만 반환하세요."

_DECOMPOSE_PROMPT = """\
다음 목표를 달성하기 위한 실행 단계를 JSON 배열로 반환하세요.

목표: {goal}
{context_block}
규칙:
- step_type: "python" (파이썬 코드), "shell" (CMD), "think" (판단/분석, content 없음)
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
- GUI/브라우저 자동화에는 `open_url`, `open_path`, `launch_app`, `wait_seconds`, `click_screen`, `move_mouse`, `type_text`, `press_keys`, `hotkey`, `take_screenshot`, `read_clipboard`, `write_clipboard`, `wait_for_window`, `get_active_window_title`, `browser_login` 헬퍼를 사용할 수 있습니다.
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
- GUI/브라우저 자동화가 필요하면 가능한 한 내장 헬퍼(`open_url`, `launch_app`, `click_screen`, `type_text`, `wait_for_window`, `browser_login` 등)를 사용하세요.
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


class AgentPlanner:
    """목표 분해 / 단계 수정 / 결과 검증 플래너"""

    def __init__(self, llm_provider):
        self.llm = llm_provider

    # ── 공개 API ──────────────────────────────────────────────────────────────

    def decompose(self, goal: str, context: Dict[str, str] = None) -> List[ActionStep]:
        """목표를 실행 단계 목록으로 분해 (전략 기억 컨텍스트 포함)"""
        templated = self._build_template_plan(goal)
        if templated:
            logging.info(f"[Planner] 템플릿 계획 사용: {goal}")
            return templated

        # 과거 전략 기억 주입
        strategy_ctx = self._get_strategy_context(goal)
        ctx_block = self._fmt_context(context)
        if strategy_ctx:
            ctx_block = strategy_ctx + "\n" + ctx_block

        prompt = _DECOMPOSE_PROMPT.format(goal=goal, context_block=ctx_block)
        raw = self._call_llm(prompt)
        self._write_trace("decompose", goal, raw)
        items = self._parse_array(raw)
        if not items:
            logging.warning(f"[Planner] decompose 파싱 실패: {raw[:200]}")
            return []
        return [
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

    def _build_template_plan(self, goal: str) -> List[ActionStep]:
        """LLM이 자주 실패하는 검색-요약-저장 계열 작업은 안정적인 템플릿으로 우선 처리."""
        profile = self._profile_goal(goal)

        if profile.wants_system_info and profile.wants_save:
            return self._build_system_info_plan(profile)

        if profile.wants_open and (profile.url or profile.source_path or profile.target_name not in {"result", "summary"}):
            return self._build_open_target_plan(profile)

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
        path_tail_pattern = r'\s+(?:로|에|를|으로|후|하고|목록|리스트|저장|보여줘|나열|파일|폴더|디렉토리|요약|정리|복사|이동)\b'
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
        elif "탐색기" in normalized or "explorer" in lower:
            target_name = "explorer"

        return GoalProfile(
            normalized_goal=normalized,
            wants_save=any(token in normalized for token in ("저장", "파일", "문서", "내보내기")),
            wants_summary=any(token in normalized for token in ("요약", "정리", "보고", "리포트")),
            wants_search=any(token in normalized for token in ("검색", "찾아", "조사", "뉴스", "웹", "인터넷")),
            wants_news="뉴스" in normalized,
            wants_desktop="바탕화면" in normalized or "desktop" in lower,
            wants_folder="폴더" in normalized or "디렉토리" in normalized,
            wants_file="파일" in normalized or bool(source_path),
            wants_system_info=any(token in normalized for token in ("시스템 정보", "pc 정보", "컴퓨터 정보", "사양", "process", "프로세스")),
            wants_copy=any(token in normalized for token in ("복사", "copy")),
            wants_move=any(token in normalized for token in ("이동", "옮겨", "move")),
            wants_list=any(token in normalized for token in ("목록", "리스트", "나열", "보여줘")),
            wants_delete=any(token in normalized for token in ("삭제", "지워", "제거")),
            wants_open=any(token in normalized for token in ("열어", "실행", "켜", "오픈", "launch", "open")),
            wants_login=any(token in normalized for token in ("로그인", "sign in", "login")),
            wants_browser=bool(url) or any(token in normalized for token in ("브라우저", "사이트", "웹", "크롬", "엣지")),
            source_path=source_path,
            destination_path=destination_path,
            url=url,
            target_name=target_name,
            preferred_format=preferred_format,
        )

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
        title = "시스템 정보 보고서"
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
                description_kr="보고서 폴더 준비",
                expected_output="folder path",
                on_failure="abort",
            ),
            ActionStep(
                step_id=1,
                step_type="python",
                content=(
                    "import os\n"
                    "import platform\n"
                    "import psutil\n"
                    "lines = ['# 시스템 정보 보고서', '']\n"
                    "lines.append(f'- OS: {platform.platform()}')\n"
                    "lines.append(f'- Python: {platform.python_version()}')\n"
                    "lines.append(f'- CPU 코어: {psutil.cpu_count(logical=True)}')\n"
                    "vm = psutil.virtual_memory()\n"
                    "lines.append(f'- 메모리: {round(vm.total / (1024**3), 2)} GB')\n"
                    "disk = psutil.disk_usage(os.path.expanduser('~'))\n"
                    "lines.append(f'- 디스크 사용률: {disk.percent}%')\n"
                    "lines.append('')\n"
                    "lines.append('## 실행 중 프로세스 상위 10개')\n"
                    "for proc in sorted(psutil.process_iter(['name', 'memory_info']), key=lambda p: (p.info['memory_info'].rss if p.info['memory_info'] else 0), reverse=True)[:10]:\n"
                    "    mem = proc.info['memory_info'].rss / (1024**2) if proc.info['memory_info'] else 0\n"
                    "    lines.append(f'- {proc.info[\"name\"]}: {mem:.1f} MB')\n"
                    "report = '\\n'.join(lines)\n"
                    "print(report)"
                ),
                description_kr="시스템 정보 수집",
                expected_output="system info markdown",
                condition="len(step_outputs.get('step_0_output', '')) > 0",
                on_failure="abort",
            ),
            ActionStep(
                step_id=2,
                step_type="python",
                content=(
                    "folder_path = step_outputs.get('step_0_output', '').strip()\n"
                    "report = step_outputs.get('step_1_output', '')\n"
                    f"saved_path = save_document(folder_path, 'system_report', report, preferred_format={json.dumps(profile.preferred_format)}, title={json.dumps(title, ensure_ascii=False)})\n"
                    "print(saved_path)"
                ),
                description_kr="시스템 정보 저장",
                expected_output="saved report path",
                condition="len(step_outputs.get('step_1_output', '')) > 0",
                on_failure="abort",
            ),
        ]

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
        """실패한 단계를 LLM으로 수정"""
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
        raw = self._call_llm(prompt)
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
        """실행 결과가 목표를 달성했는지 검증 (LLM 텍스트 기반 폴백용)"""
        lines = []
        for i, r in enumerate(step_results):
            status = "성공" if r.success else "실패"
            out = r.output[:150] if r.output else (r.error[:150] if r.error else "없음")
            lines.append(f"  단계 {i+1} [{status}]: {out}")
        results_summary = "\n".join(lines)
        prompt = _VERIFY_PROMPT.format(goal=goal, results_summary=results_summary)
        raw = self._call_llm(prompt)
        self._write_trace("verify", goal, raw)
        data = self._parse_object(raw)
        return data if data else {"achieved": False, "summary_kr": "검증 실패"}

    # ── 내부 ──────────────────────────────────────────────────────────────────

    def _get_strategy_context(self, goal: str) -> str:
        """전략 기억에서 유사 과거 경험 조회 (실패 무시)"""
        try:
            from strategy_memory import get_strategy_memory
            return get_strategy_memory().get_relevant_context(goal)
        except Exception:
            return ""

    def _get_failure_hints(self, goal: str) -> str:
        """최근 실패 패턴 요약 문자열 반환"""
        try:
            from strategy_memory import get_strategy_memory
            failures = get_strategy_memory().recent_failures(goal)
            return "\n".join(f"- {f}" for f in failures) if failures else ""
        except Exception:
            return ""

    def _call_llm(self, prompt: str) -> str:
        """대화 히스토리와 독립적으로 LLM 호출 (planning 전용)"""
        try:
            if not self.llm.client:
                return ""
            if self.llm.provider == "anthropic":
                resp = self.llm.client.messages.create(
                    model=self.llm.model,
                    max_tokens=1000,
                    system=_SYS_JSON_ONLY,
                    messages=[{"role": "user", "content": prompt}],
                )
                return " ".join(b.text for b in resp.content if b.type == "text")
            else:
                resp = self.llm.client.chat.completions.create(
                    model=self.llm.model,
                    messages=[
                        {"role": "system", "content": _SYS_JSON_ONLY},
                        {"role": "user", "content": prompt},
                    ],
                    temperature=0.1,
                    max_tokens=1000,
                )
                return resp.choices[0].message.content or ""
        except Exception as e:
            logging.error(f"[Planner] LLM 호출 오류: {e}")
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
        from llm_provider import get_llm_provider
        _planner = AgentPlanner(get_llm_provider())
    return _planner
