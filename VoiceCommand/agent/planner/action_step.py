"""
ActionStep / GoalProfile 데이터클래스 — 플래너가 사용하는 핵심 타입.
"""
from dataclasses import dataclass, field
from typing import List


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
    optional: bool = False


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
