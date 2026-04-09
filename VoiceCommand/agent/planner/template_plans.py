"""
TemplatePlansMixin — GoalProfile 기반 템플릿 플랜 생성 메서드 모음.

AgentPlanner가 이 믹스인을 상속하여 _build_template_plan() 및
모든 _build_*_plan() 메서드를 사용한다.
"""
import json
import os
import re
from typing import Dict, List

from agent.planner.action_step import ActionStep, GoalProfile

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


class TemplatePlansMixin:
    """GoalProfile 기반 템플릿 플랜 생성 메서드 모음."""

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
        """URL·경로·앱 이름을 대상으로 열기/실행하는 플랜 생성."""
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
        """브라우저에서 특정 URL의 파일을 다운로드하는 플랜 생성."""
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
        """브라우저 현재 페이지의 링크를 수집하는 플랜 생성."""
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
        """브라우저 페이지의 링크를 수집해 파일로 저장하는 플랜 생성."""
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
        """특정 사이트 URL을 열고 로그인을 준비하는 플랜 생성."""
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
        """사이트에 로그인한 뒤 링크를 수집하는 결합 플랜 생성."""
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
        """브라우저 열기 → 텍스트 입력 → 제출하는 플랜 생성."""
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
        """브라우저에 텍스트를 입력하고 결과 페이지를 파일로 저장하는 플랜 생성."""
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
        """단일 파일/폴더 이름을 변경하는 플랜 생성."""
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
        """폴더 내 파일들을 규칙에 따라 일괄 이름 변경하는 플랜 생성."""
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
        """폴더 내 파일 세트를 스캔해 확장자 통계를 생성하는 플랜 생성."""
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
        """메모장·탐색기·크롬 등 바탕화면 앱을 실행하고 준비 상태를 확인하는 플랜 생성."""
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
        """여러 파일을 하나로 병합해 저장하는 플랜 생성."""
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
        """폴더 내 파일을 확장자별로 하위 폴더에 분류·정리하는 플랜 생성."""
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
        """파일 데이터를 통계·구조 분석하고 보고서로 저장하는 플랜 생성."""
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
        """로그 파일을 분석해 요약 리포트를 생성·저장하는 플랜 생성."""
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
        """지정한 이름으로 새 폴더를 생성하는 플랜 생성."""
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
        """현재 열린 창 목록을 요약해 파일로 저장하는 플랜 생성."""
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
        """파일/폴더를 복사 또는 이동하는 플랜 생성 (move=True이면 이동, False이면 복사)."""
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
        """시스템 정보 또는 보안 점검 결과를 수집하고 보고서로 저장하는 플랜 생성."""
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
        """디렉터리 목록을 수집해 파일로 저장하는 플랜 생성."""
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
        """파일 내용을 읽어 요약하고 결과를 저장하는 플랜 생성."""
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
        """웹 검색 결과를 요약해 파일로 저장하는 플랜 생성."""
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

