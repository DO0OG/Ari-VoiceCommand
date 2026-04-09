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
_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9+-]{1,}|[가-힣]{2,}|[ぁ-んァ-ヶー一-龯]{2,}")
_COMMON_KEYWORD_STOPWORDS = {
    "the", "and", "for", "with", "from", "that", "this", "when", "what", "where",
    "which", "into", "your", "user", "asks", "ask", "using", "used", "then", "first",
    "through", "after", "before", "want", "wants", "need", "needs", "show", "tell",
    "lookup", "look", "results", "result", "guide", "setup", "skill", "skills",
    "official", "query", "today", "yesterday", "specific", "always", "current",
    "nearby", "based", "later",
}
_SKILL_FRONTMATTER_OVERRIDES: Dict[str, dict] = {
    "lck-analytics": {
        "skill_type": "search",
        "description_ko": "Riot 공식 LoL Esports 데이터로 LCK 경기 결과, 순위, 밴픽 분석을 조회한다.",
        "description_en": "Retrieve LCK match results, standings, and ban/pick analysis from Riot official LoL Esports data.",
        "description_ja": "Riot公式LoLエスポーツデータでLCKの試合結果・順位・バンピック分析を取得する。",
        "triggers_ko": ["LCK", "경기 결과", "롤챔스", "리그 오브 레전드 챔피언십"],
        "triggers_en": ["LCK", "match result", "match results", "lol esports", "league of legends championship korea"],
        "triggers_ja": ["LCK", "試合結果", "リーグオブレジェンド", "eスポーツ"],
        "search_query_template_ko": "LCK {date} 경기 결과",
        "search_query_template_en": "LCK {date} match results",
        "search_query_template_ja": "LCK {date} 試合結果",
    },
    "kbo-results": {
        "skill_type": "search",
        "description_ko": "KBO 경기 일정과 결과를 날짜 기준으로 조회한다.",
        "description_en": "Fetch KBO schedules and results for a requested date.",
        "description_ja": "KBOの試合日程と結果を日付基準で取得する。",
        "triggers_ko": ["KBO", "경기 결과", "야구 결과"],
        "triggers_en": ["KBO", "baseball results", "game results"],
        "triggers_ja": ["KBO", "試合結果", "野球結果"],
        "search_query_template_ko": "KBO {date} 경기 결과",
        "search_query_template_en": "KBO {date} game results",
        "search_query_template_ja": "KBO {date} 試合結果",
    },
    "kleague-results": {
        "skill_type": "search",
        "description_ko": "K리그 경기 결과와 현재 순위를 날짜 또는 팀 기준으로 조회한다.",
        "description_en": "Retrieve K League match results and standings by date or team.",
        "description_ja": "Kリーグの試合結果と順位を日付またはチーム基準で取得する。",
        "triggers_ko": ["K리그", "경기 결과", "순위"],
        "triggers_en": ["K League", "match results", "standings"],
        "triggers_ja": ["Kリーグ", "試合結果", "順位"],
        "search_query_template_ko": "K리그 {date} 경기 결과",
        "search_query_template_en": "K League {date} match results",
        "search_query_template_ja": "Kリーグ {date} 試合結果",
    },
    "lotto-results": {
        "skill_type": "search",
        "description_ko": "한국 로또 당첨 번호와 회차 결과를 조회한다.",
        "description_en": "Check Korean Lotto winning numbers and round results.",
        "description_ja": "韓国ロトの当選番号と回次結果を取得する。",
        "triggers_ko": ["로또", "당첨 번호", "당첨번호"],
        "triggers_en": ["lotto", "winning numbers", "draw results"],
        "triggers_ja": ["ロト", "当選番号", "抽選結果"],
        "search_query_template_ko": "로또 {date} 당첨 번호",
        "search_query_template_en": "Korean Lotto {date} winning numbers",
        "search_query_template_ja": "韓国ロト {date} 当選番号",
    },
    "korea-weather": {
        "skill_type": "search",
        "description_ko": "한국 날씨를 지역 기준으로 조회해 요약한다.",
        "description_en": "Retrieve and summarize Korea weather by location.",
        "description_ja": "韓国の天気を地域基準で取得して要約する。",
        "triggers_ko": ["날씨", "기상", "온도"],
        "triggers_en": ["weather", "forecast", "temperature"],
        "triggers_ja": ["天気", "予報", "気温"],
        "search_query_template_ko": "한국 {date} 날씨",
        "search_query_template_en": "Korea {date} weather",
        "search_query_template_ja": "韓国 {date} 天気",
    },
    "korean-stock-search": {
        "skill_type": "search",
        "description_ko": "한국 상장 종목 검색과 기본 정보, 일별 시세를 조회한다.",
        "description_en": "Search Korean listed stocks and retrieve basic info and daily prices.",
        "description_ja": "韓国上場銘柄を検索し、基本情報と日次価格を取得する。",
        "triggers_ko": ["주가", "종목", "한국 주식"],
        "triggers_en": ["stock price", "korean stock", "ticker"],
        "triggers_ja": ["株価", "韓国株", "銘柄"],
        "search_query_template_ko": "한국 주식 {date} 시세",
        "search_query_template_en": "Korean stock {date} price",
        "search_query_template_ja": "韓国株 {date} 株価",
    },
    "blue-ribbon-nearby": {
        "triggers_ko": ["블루리본", "근처 맛집", "맛집 추천"],
        "triggers_en": ["blue ribbon", "nearby restaurants", "restaurant picks"],
        "triggers_ja": ["ブルーリボン", "近くのグルメ", "おすすめレストラン"],
    },
    "bunjang-search": {
        "triggers_ko": ["번개장터", "번장", "중고거래"],
        "triggers_en": ["bunjang", "used marketplace", "secondhand search"],
        "triggers_ja": ["ポンジャン", "中古取引", "中古マーケット"],
    },
    "cheap-gas-nearby": {
        "triggers_ko": ["주유소", "가장 싼 주유소", "기름값"],
        "triggers_en": ["cheap gas", "gas station", "fuel price"],
        "triggers_ja": ["安いガソリンスタンド", "ガソリン価格", "給油所"],
    },
    "coupang-product-search": {
        "triggers_ko": ["쿠팡", "로켓배송", "상품 검색"],
        "triggers_en": ["coupang", "rocket delivery", "product search"],
        "triggers_ja": ["クーパン", "ロケット配送", "商品検索"],
    },
    "daiso-product-search": {
        "triggers_ko": ["다이소", "다이소 재고", "다이소 상품"],
        "triggers_en": ["daiso", "daiso stock", "daiso product"],
        "triggers_ja": ["ダイソー", "ダイソー在庫", "ダイソー商品"],
    },
    "delivery-tracking": {
        "triggers_ko": ["택배 조회", "운송장", "배송 추적"],
        "triggers_en": ["delivery tracking", "tracking number", "parcel tracking"],
        "triggers_ja": ["配送追跡", "追跡番号", "宅配追跡"],
    },
    "fine-dust-location": {
        "triggers_ko": ["미세먼지", "초미세먼지", "대기질"],
        "triggers_en": ["fine dust", "air quality", "pm10"],
        "triggers_ja": ["微細粉塵", "大気質", "pm2.5"],
    },
    "han-river-water-level": {
        "triggers_ko": ["한강 수위", "수위", "유량"],
        "triggers_en": ["han river water level", "water level", "river flow"],
        "triggers_ja": ["漢江水位", "水位", "流量"],
    },
    "hipass-receipt": {
        "triggers_ko": ["하이패스", "영수증", "통행료"],
        "triggers_en": ["hipass", "toll receipt", "toll history"],
        "triggers_ja": ["ハイパス", "領収書", "通行料"],
    },
    "household-waste-info": {
        "triggers_ko": ["생활쓰레기", "쓰레기 배출", "분리수거"],
        "triggers_en": ["household waste", "garbage schedule", "recycling"],
        "triggers_ja": ["生活ごみ", "ごみ出し", "分別回収"],
    },
    "hwp": {
        "triggers_ko": ["한글 파일", "hwp", "문서 변환"],
        "triggers_en": ["hwp", "hangul document", "document conversion"],
        "triggers_ja": ["hwp", "ハングル文書", "文書変換"],
    },
    "joseon-sillok-search": {
        "triggers_ko": ["조선왕조실록", "실록", "사료"],
        "triggers_en": ["joseon annals", "sillok", "historical records"],
        "triggers_ja": ["朝鮮王朝実録", "実録", "史料"],
    },
    "k-skill-setup": {
        "triggers_ko": ["k-skill", "스킬 설정", "설치 확인"],
        "triggers_en": ["k-skill setup", "skill setup", "bundle setup"],
        "triggers_ja": ["k-skill セットアップ", "スキル設定", "インストール確認"],
    },
    "kakao-bar-nearby": {
        "triggers_ko": ["근처 술집", "술집", "바 추천"],
        "triggers_en": ["nearby bar", "bars nearby", "bar recommendation"],
        "triggers_ja": ["近くのバー", "居酒屋", "バーおすすめ"],
    },
    "kakaotalk-mac": {
        "triggers_ko": ["카카오톡", "카톡", "메시지 검색"],
        "triggers_en": ["kakaotalk", "kakao talk", "message search"],
        "triggers_ja": ["カカオトーク", "メッセージ検索", "カカオ"],
    },
    "korean-law-search": {
        "triggers_ko": ["법령", "조문", "판례"],
        "triggers_en": ["korean law", "statute", "case law"],
        "triggers_ja": ["韓国法", "条文", "判例"],
    },
    "korean-patent-search": {
        "triggers_ko": ["특허", "키프리스", "실용신안"],
        "triggers_en": ["patent", "kipris", "utility model"],
        "triggers_ja": ["特許", "キプリス", "実用新案"],
    },
    "korean-spell-check": {
        "triggers_ko": ["맞춤법", "띄어쓰기", "교정"],
        "triggers_en": ["spell check", "proofread korean", "spacing check"],
        "triggers_ja": ["スペルチェック", "韓国語校正", "表記修正"],
    },
    "ktx-booking": {
        "triggers_ko": ["KTX", "기차 예매", "코레일"],
        "triggers_en": ["ktx booking", "korail", "train booking"],
        "triggers_ja": ["KTX", "列車予約", "コレール"],
    },
    "olive-young-search": {
        "triggers_ko": ["올리브영", "올영", "재고 확인"],
        "triggers_en": ["olive young", "oliveyoung", "store stock"],
        "triggers_ja": ["オリーブヤング", "在庫確認", "商品検索"],
    },
    "real-estate-search": {
        "triggers_ko": ["부동산", "실거래가", "전세"],
        "triggers_en": ["real estate", "housing price", "rent price"],
        "triggers_ja": ["不動産", "実取引価格", "賃貸相場"],
    },
    "seoul-subway-arrival": {
        "triggers_ko": ["지하철 도착", "서울 지하철", "열차 도착"],
        "triggers_en": ["seoul subway", "subway arrival", "train arrival"],
        "triggers_ja": ["ソウル地下鉄", "地下鉄到着", "列車到着"],
    },
    "srt-booking": {
        "triggers_ko": ["SRT", "SRT 예약", "수서고속철도"],
        "triggers_en": ["srt booking", "srt ticket", "suseo rail"],
        "triggers_ja": ["SRT", "SRT予約", "高速鉄道"],
    },
    "toss-securities": {
        "triggers_ko": ["토스증권", "포트폴리오", "계좌 조회"],
        "triggers_en": ["toss securities", "portfolio", "account summary"],
        "triggers_ja": ["トス証券", "ポートフォリオ", "口座照会"],
    },
    "used-car-price-search": {
        "triggers_ko": ["중고차", "자동차 시세", "중고차 가격"],
        "triggers_en": ["used car", "car price", "used car price"],
        "triggers_ja": ["中古車", "中古車価格", "車両相場"],
    },
    "zipcode-search": {
        "triggers_ko": ["우편번호", "주소 우편번호", "도로명 우편번호"],
        "triggers_en": ["zipcode", "postal code", "postcode"],
        "triggers_ja": ["郵便番号", "住所郵便番号", "ポストコード"],
    },
}


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
    skill_type: str = "prompt_only"
    search_query_templates: Dict[str, str] = field(default_factory=dict)
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
                "force_web_search": False,
                "escalate_to_agent": False,
                "search_query_template": "",
            }
        from i18n.translator import get_language

        lang = get_language()
        force_web_search = any(skill.skill_type == "search" for skill in matched)
        escalate_to_agent = any(skill.skill_type == "script" for skill in matched)
        required_tool_names = {"mcp_call"} if any(skill.is_mcp_skill for skill in matched) else set()
        if force_web_search:
            required_tool_names.add("web_search")
        search_query_template = ""
        for skill in matched:
            if skill.skill_type != "search":
                continue
            search_query_template = (
                skill.search_query_templates.get(lang, "")
                or skill.search_query_templates.get("ko", "")
                or next(iter(skill.search_query_templates.values()), "")
            )
            if search_query_template:
                break
        preferred_tool = "mcp_call" if any(skill.is_mcp_skill for skill in matched) else ("web_search" if force_web_search else "")
        return {
            "skills": matched,
            "prompt": self._build_prompt(matched),
            "required_tool_names": sorted(required_tool_names),
            "preferred_tool": preferred_tool,
            "force_web_search": force_web_search,
            "escalate_to_agent": escalate_to_agent,
            "search_query_template": search_query_template,
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
        meta = self._apply_frontmatter_overrides(skill_name, meta)
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
            skill_type=self._resolve_skill_type(meta, endpoint),
            search_query_templates=self._extract_search_query_templates(meta),
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
        try:
            from i18n.translator import get_language

            lang = get_language()
        except Exception as exc:
            logger.debug("[SkillManager] 언어 설정 조회 실패, ko 기본값 사용: %s", exc)
            lang = "ko"
        for key in (f"description_{lang}", "description"):
            description = str(meta.get(key, "") or "").strip()
            if description:
                return description
        for line in body.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or stripped.startswith(">"):
                continue
            return stripped[:140]
        return fallback_name

    def _extract_keywords(self, meta: dict, skill_name: str, entry: str) -> List[str]:
        try:
            from i18n.translator import get_language

            lang = get_language()
        except Exception as exc:
            logger.debug("[SkillManager] 언어 설정 조회 실패, ko 기본값 사용: %s", exc)
            lang = "ko"
        collected: List[str] = []
        for key in (f"triggers_{lang}", "triggers", "keywords", "trigger_keywords"):
            value = meta.get(key)
            if isinstance(value, list):
                collected.extend(str(item).strip() for item in value if str(item).strip())
            elif value:
                collected.extend(
                    token.strip()
                    for token in re.split(r"[,/|]", str(value))
                    if token.strip()
                )
            if collected and key.startswith("triggers_"):
                break
        if not collected:
            collected.extend(self._extract_fallback_keywords(meta, skill_name))
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

    def _resolve_skill_type(self, meta: dict, endpoint: Optional[str]) -> str:
        if endpoint:
            return "mcp"
        raw_value = self._normalize_text(meta.get("skill_type", ""))
        if raw_value in {"prompt_only", "search", "script", "mcp"}:
            return raw_value
        return "prompt_only"

    def _extract_search_query_templates(self, meta: dict) -> Dict[str, str]:
        templates: Dict[str, str] = {}
        for lang in ("ko", "en", "ja"):
            value = str(meta.get(f"search_query_template_{lang}", "") or "").strip()
            if value:
                templates[lang] = value
        fallback = str(meta.get("search_query_template", "") or "").strip()
        if fallback:
            templates.setdefault("ko", fallback)
        return templates

    def _extract_fallback_keywords(self, meta: dict, skill_name: str) -> List[str]:
        candidates: List[str] = []
        for key, value in meta.items():
            if not isinstance(key, str):
                continue
            normalized_key = key.lower()
            if normalized_key.startswith("description"):
                candidates.extend(self._tokenize_keyword_source(value))
            elif normalized_key.startswith("triggers"):
                if isinstance(value, list):
                    for item in value:
                        candidates.extend(self._tokenize_keyword_source(item))
                else:
                    candidates.extend(self._tokenize_keyword_source(value))
        if not candidates:
            candidates.extend(self._tokenize_keyword_source(skill_name))
        return candidates

    def _tokenize_keyword_source(self, value) -> List[str]:
        tokens: List[str] = []
        source = str(value or "")
        for token in _TOKEN_RE.findall(source):
            if token.lower() in _COMMON_KEYWORD_STOPWORDS:
                continue
            tokens.append(token)
        return tokens

    def _apply_frontmatter_overrides(self, skill_name: str, meta: dict) -> dict:
        overrides = _SKILL_FRONTMATTER_OVERRIDES.get(str(skill_name or "").strip(), {})
        if not overrides:
            return meta
        merged = dict(overrides)
        merged.update(meta)
        return merged

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


try:
    from i18n.translator import on_language_changed

    on_language_changed(reset_skill_manager)
except Exception as exc:
    logger.debug("[SkillManager] 언어 변경 콜백 등록 생략: %s", exc)
