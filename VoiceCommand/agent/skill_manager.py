"""SKILL.md 기반 에이전트 스킬 관리자."""
from __future__ import annotations

import json
import logging
import os
import re
import shutil
import threading
from dataclasses import dataclass, field
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

_SKILLS_DIR_NAME = "skills"
_SKILL_FILE_NAME = "SKILL.md"
_META_FILE_NAME = ".ari_skill_meta.json"
_FRONTMATTER_LINE_RE = re.compile(r"^([A-Za-z0-9_-]+):\s*(.*)$")
_MCP_ENDPOINT_RE = re.compile(r"(https://[^\s)>'\"`]+/mcp)\b", re.IGNORECASE)
_MCP_TOOL_RE = re.compile(r"\b([A-Za-z][A-Za-z0-9_]{2,})\b")


def _get_skills_dir() -> str:
    try:
        from core.resource_manager import ResourceManager

        return ResourceManager.get_writable_path(_SKILLS_DIR_NAME)
    except Exception as exc:
        logger.debug("[SkillManager] skills 경로 조회 실패, 로컬 폴백 사용: %s", exc)
        return os.path.join(os.path.dirname(os.path.dirname(__file__)), _SKILLS_DIR_NAME)


@dataclass
class SkillInfo:
    name: str
    skill_dir: str
    description: str
    trigger_keywords: List[str]
    content: str
    mcp_endpoint: Optional[str] = None
    scripts_dir: Optional[str] = None
    enabled: bool = True
    source: str = ""
    mcp_tools: List[str] = field(default_factory=list)

    @property
    def is_mcp_skill(self) -> bool:
        return bool(self.mcp_endpoint)

    @property
    def metadata_path(self) -> str:
        return os.path.join(self.skill_dir, _META_FILE_NAME)


class SkillManager:
    """설치된 에이전트 스킬 목록을 관리한다."""

    def __init__(self):
        self._skills: Dict[str, SkillInfo] = {}
        self._lock = threading.RLock()
        self.skills_dir = _get_skills_dir()
        os.makedirs(self.skills_dir, exist_ok=True)
        self.load_all()

    def load_all(self) -> List[SkillInfo]:
        loaded: List[SkillInfo] = []
        with self._lock:
            self._skills.clear()
            os.makedirs(self.skills_dir, exist_ok=True)
            for entry in sorted(os.listdir(self.skills_dir)):
                skill_dir = os.path.join(self.skills_dir, entry)
                skill_md = os.path.join(skill_dir, _SKILL_FILE_NAME)
                if not os.path.isdir(skill_dir) or not os.path.isfile(skill_md):
                    continue
                try:
                    skill = self._parse_skill(entry, skill_dir, skill_md)
                except Exception as exc:
                    logger.warning("[SkillManager] 스킬 로드 실패 (%s): %s", entry, exc)
                    continue
                self._skills[skill.name] = skill
                loaded.append(skill)
        return loaded

    def list_skills(self) -> List[SkillInfo]:
        with self._lock:
            return sorted(self._skills.values(), key=lambda item: item.name.lower())

    def get_skill(self, name: str) -> Optional[SkillInfo]:
        with self._lock:
            return self._skills.get(name)

    def enable(self, name: str) -> bool:
        return self._set_enabled(name, True)

    def disable(self, name: str) -> bool:
        return self._set_enabled(name, False)

    def remove(self, name: str) -> bool:
        with self._lock:
            skill = self._skills.pop(name, None)
        if not skill:
            return False
        try:
            shutil.rmtree(skill.skill_dir)
        except FileNotFoundError:
            pass
        return True

    def match_skills(self, user_message: str) -> List[SkillInfo]:
        normalized = self._normalize_text(user_message)
        if not normalized:
            return []

        ranked: list[tuple[int, SkillInfo]] = []
        for skill in self.list_skills():
            if not skill.enabled:
                continue
            score = 0
            for keyword in skill.trigger_keywords:
                token = self._normalize_text(keyword)
                if token and token in normalized:
                    score += max(len(token), 3)
            name_token = self._normalize_text(skill.name)
            if name_token and name_token in normalized:
                score += max(len(name_token), 4)
            if score > 0:
                ranked.append((score, skill))
        ranked.sort(key=lambda item: (-item[0], item[1].name.lower()))
        return [skill for _, skill in ranked[:3]]

    def build_match_context(self, user_message: str) -> dict:
        matched = self.match_skills(user_message)
        if not matched:
            return {
                "skills": [],
                "prompt": "",
                "required_tool_names": [],
                "preferred_tool": "",
            }
        required_tool_names = {"mcp_call"} if any(skill.is_mcp_skill for skill in matched) else set()
        preferred_tool = "mcp_call" if required_tool_names else ""
        return {
            "skills": matched,
            "prompt": self._build_prompt(matched),
            "required_tool_names": sorted(required_tool_names),
            "preferred_tool": preferred_tool,
        }

    def _set_enabled(self, name: str, enabled: bool) -> bool:
        with self._lock:
            skill = self._skills.get(name)
            if not skill:
                return False
            skill.enabled = enabled
            self._write_metadata(skill, {"enabled": enabled, "source": skill.source})
            return True

    def _parse_skill(self, entry: str, skill_dir: str, skill_md: str) -> SkillInfo:
        with open(skill_md, "r", encoding="utf-8") as handle:
            raw_content = handle.read()

        frontmatter, body = self._split_frontmatter(raw_content)
        meta = self._parse_frontmatter(frontmatter)
        skill_name = str(meta.get("name") or entry).strip() or entry
        description = self._extract_description(meta, body, skill_name)
        keywords = self._extract_keywords(meta, skill_name, entry)
        scripts_dir = os.path.join(skill_dir, "scripts")
        endpoint = self._extract_mcp_endpoint(raw_content)
        metadata = self._read_metadata(skill_dir)
        return SkillInfo(
            name=skill_name,
            skill_dir=skill_dir,
            description=description,
            trigger_keywords=keywords,
            content=raw_content,
            mcp_endpoint=endpoint,
            scripts_dir=scripts_dir if os.path.isdir(scripts_dir) else None,
            enabled=bool(metadata.get("enabled", True)),
            source=str(metadata.get("source", "") or ""),
            mcp_tools=self._extract_mcp_tools(raw_content),
        )

    def _split_frontmatter(self, content: str) -> tuple[str, str]:
        normalized = content.lstrip()
        if not normalized.startswith("---"):
            return "", content
        lines = normalized.splitlines()
        end_index = None
        for index in range(1, len(lines)):
            if lines[index].strip() == "---":
                end_index = index
                break
        if end_index is None:
            return "", content
        frontmatter = "\n".join(lines[1:end_index])
        body = "\n".join(lines[end_index + 1 :])
        return frontmatter, body

    def _parse_frontmatter(self, frontmatter: str) -> dict:
        if not frontmatter.strip():
            return {}
        parsed: dict[str, object] = {}
        current_key = ""
        for raw_line in frontmatter.splitlines():
            line = raw_line.rstrip()
            if not line.strip():
                continue
            match = _FRONTMATTER_LINE_RE.match(line)
            if match:
                current_key = match.group(1).strip().lower()
                value = match.group(2).strip()
                if value.startswith("[") and value.endswith("]"):
                    items = [
                        item.strip().strip("'\"")
                        for item in value[1:-1].split(",")
                        if item.strip()
                    ]
                    parsed[current_key] = items
                elif value == "":
                    parsed[current_key] = []
                else:
                    parsed[current_key] = value.strip("'\"")
                continue
            if current_key and line.lstrip().startswith("- "):
                parsed.setdefault(current_key, [])
                if isinstance(parsed[current_key], list):
                    parsed[current_key].append(line.split("- ", 1)[1].strip().strip("'\""))
        return parsed

    def _extract_description(self, meta: dict, body: str, fallback_name: str) -> str:
        description = str(meta.get("description", "") or "").strip()
        if description:
            return description
        for line in body.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or stripped.startswith(">"):
                continue
            return stripped[:140]
        return fallback_name

    def _extract_keywords(self, meta: dict, skill_name: str, entry: str) -> List[str]:
        collected: List[str] = []
        for key in ("triggers", "keywords", "trigger_keywords"):
            value = meta.get(key)
            if isinstance(value, list):
                collected.extend(str(item).strip() for item in value if str(item).strip())
            elif value:
                collected.extend(
                    token.strip()
                    for token in re.split(r"[,/|]", str(value))
                    if token.strip()
                )
        if not collected:
            for token in re.split(r"[-_\s]+", f"{skill_name} {entry}"):
                cleaned = token.strip()
                if len(cleaned) >= 2:
                    collected.append(cleaned)
        deduped: List[str] = []
        seen: set[str] = set()
        for token in collected:
            normalized = self._normalize_text(token)
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            deduped.append(token)
        return deduped

    def _extract_mcp_endpoint(self, content: str) -> Optional[str]:
        match = _MCP_ENDPOINT_RE.search(content or "")
        return match.group(1) if match else None

    def _extract_mcp_tools(self, content: str) -> List[str]:
        tools: List[str] = []
        for line in str(content or "").splitlines():
            if "tool" not in line.lower() and "mcp_call" not in line.lower():
                continue
            for token in _MCP_TOOL_RE.findall(line):
                if token.startswith("http") or token.lower() in {"tool", "tools", "mcp_call"}:
                    continue
                if token not in tools:
                    tools.append(token)
        return tools[:8]

    def _read_metadata(self, skill_dir: str) -> dict:
        meta_path = os.path.join(skill_dir, _META_FILE_NAME)
        try:
            with open(meta_path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
            return data if isinstance(data, dict) else {}
        except FileNotFoundError:
            return {}
        except Exception as exc:
            logger.debug("[SkillManager] 메타데이터 로드 실패 (%s): %s", skill_dir, exc)
            return {}

    def _write_metadata(self, skill: SkillInfo, metadata: dict) -> None:
        payload = {
            "enabled": bool(metadata.get("enabled", True)),
            "source": str(metadata.get("source", "") or ""),
        }
        os.makedirs(skill.skill_dir, exist_ok=True)
        with open(skill.metadata_path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)

    def _build_prompt(self, matched: List[SkillInfo]) -> str:
        from i18n.translator import _

        sections = [_("[사용 가능한 스킬]")]
        for skill in matched:
            sections.append(f"## {skill.name}\n{skill.description}\n\n{skill.content.strip()}")
            if skill.scripts_dir:
                sections.append(f"{_('스킬 스크립트 경로')}: {skill.scripts_dir}")
            if skill.is_mcp_skill:
                sections.append(
                    "\n".join(
                        [
                            f"[{_('MCP 실행 안내')}]",
                            _("이 스킬은 MCP 프로토콜을 사용합니다."),
                            _("curl 명령 대신 mcp_call 도구를 사용하세요."),
                            f"endpoint: {skill.mcp_endpoint}",
                            (
                                f"{_('예시')}: mcp_call(endpoint='{skill.mcp_endpoint}', tool='{skill.mcp_tools[0]}', arguments={{}})"
                                if skill.mcp_tools
                                else ""
                            ),
                        ]
                    ).strip()
                )
        return "\n\n".join(section for section in sections if section.strip())

    def _normalize_text(self, text: str) -> str:
        return re.sub(r"\s+", " ", str(text or "").strip().lower())


_skill_manager: Optional[SkillManager] = None
_skill_manager_lock = threading.Lock()


def get_skill_manager() -> SkillManager:
    global _skill_manager
    if _skill_manager is None:
        with _skill_manager_lock:
            if _skill_manager is None:
                _skill_manager = SkillManager()
    return _skill_manager


def reset_skill_manager() -> None:
    global _skill_manager
    with _skill_manager_lock:
        _skill_manager = None
