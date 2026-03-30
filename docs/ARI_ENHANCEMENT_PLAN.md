# Ari 강화 계획 — 최종본

> **구현 담당:** Codex  
> **검증 담당:** Claude Code  
> **작성 기준:** 실제 소스코드 전체 분석 + 배포 환경(다양한 Windows PC) 고려

---

## 현재 상태 진단

### 즉시 체감되는 버그/문제

| 문제 | 위치 | 심각도 |
|------|------|--------|
| `include_context` 기본값 `False` — 메모리가 쌓여도 대화에 미반영 | `groq_assistant.py:233,354` | 🔴 높음 |
| `RPGenerator.generate()` 입력 그대로 반환 — 캐릭터 개성이 텍스트엔 없음 | `rp_generator.py` | 🔴 높음 |
| `_filter_korean_text()`가 영문자 전부 제거 — URL/코드/영문 포함 응답 손상 | `groq_assistant.py:345` | 🔴 높음 |
| 모델명 `llama-3.3-70b-versatile` 하드코딩 — 설정 변경이 실제 반영 안 됨 | `groq_assistant.py:285,405` | 🟡 중간 |
| `max_tokens=300/200` 고정 — 복잡한 답변 잘림 | `groq_assistant.py:290,408` | 🟡 중간 |
| `stream=False` 고정 — 긴 응답 시 첫 글자까지 대기 | `groq_assistant.py:292,410` | 🟡 중간 |
| 대화 히스토리 단순 `deque(50)` — 오래된 맥락 단절, 요약 없음 | `conversation_history.py` | 🟡 중간 |
| 감정 태그가 TTS에만 쓰임 — LLM 응답 생성 시 감정 미반영 | `core/VoiceCommand.py` | 🟡 중간 |
| API 오프라인 시 완전 먹통 — Edge TTS로 폴백하지 않음 | `groq_assistant.py` | 🟡 중간 |
| LLM 응답 캐싱 없음 — 동일 질문 반복 시 매번 API 호출 | `assistant/` 전체 | 🟢 낮음 |

### 아직 구현 안 된 기능

| 기능 | 현황 |
|------|------|
| Few-shot 예시 자동 주입 | 없음 — StrategyMemory가 쌓여도 플래너 프롬프트에 예시로 안 들어감 |
| 멀티 LLM 라우팅 (작업 유형별) | 플래너/실행 분리는 있으나 대화용 라우팅 없음 |
| 스킬 자동 추출/재사용 | 없음 |
| 구조화된 자기반성 | 단순 lesson 문자열만 저장 |
| SQLite FTS 메모리 검색 | JSON 선형 스캔 |
| 사용자 프로파일 추론 | fact 저장 수준, 종합 추론 없음 |
| 사용자 피드백 루프 | 없음 |
| 주기적 메모리 정리 | 단순 FIFO prune |

---

## Phase 1 — 버그 수정 + 대화 품질 즉시 개선

> 가장 빠르게 체감. 신규 파일 없이 기존 파일 수정 중심.

---

### 1-1. 한국어 필터 버그 수정

**파일:** `assistant/groq_assistant.py` (수정)

현재 `_filter_korean_text()`가 영문자를 전부 제거해서
URL, 코드, 영문 포함 응답이 손상되는 심각한 버그.

```python
# 현재 (버그)
filtered = re.sub(r'[^가-힣0-9\s.,!?~\-()%]', '', text)

# 수정 후 — 메모리 태그([FACT:] 등)만 제거, 언어 필터 제거
def _clean_response(self, text: str) -> str:
    text = re.sub(r'\[(FACT|BIO|PREF):[^\]]+\]', '', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text
```

---

### 1-2. 컨텍스트 항상 주입 + 프롬프트 구조 개선

**파일:** `assistant/groq_assistant.py` (수정)

`include_context` 기본값 `True`로 변경.
시스템 프롬프트 구조를 LLM이 잘 활용하는 순서로 재배치.

```python
# 수정 후 기본값
def chat_with_tools(self, user_message, include_context=True):
def chat(self, user_message, include_context=True):

# 시스템 프롬프트 구조 (우선순위 순)
def _build_system(self, include_context: bool) -> str:
    parts = []
    # 1. 사용자 프로파일 (최우선)
    if include_context:
        parts.append(get_user_profile_engine().get_prompt_injection())
    # 2. 기억된 사실 상위 5개
    if include_context:
        parts.append(memory_manager.get_top_facts_prompt(n=5))
    # 3. 캐릭터 personality / scenario
    parts.append(rp_gen.build_system_prompt(base_prompt))
    # 4. 도구 사용 지침
    parts.append(TOOL_INSTRUCTION)
    return "\n\n".join(filter(None, parts))
```

---

### 1-3. RPGenerator 실제 구현

**파일:** `core/rp_generator.py` (수정)

현재 `generate()`가 입력 그대로 반환. 실제로 동작하도록 구현.

```python
class RPGenerator:
    def build_system_prompt(self, base_prompt: str) -> str:
        """personality/scenario를 시스템 프롬프트에 녹임"""
        parts = [base_prompt]
        if self.personality:
            parts.append(f"[캐릭터 성격]\n{self.personality}")
        if self.scenario:
            parts.append(f"[현재 상황]\n{self.scenario}")
        if self.history_instruction:
            parts.append(f"[대화 방식]\n{self.history_instruction}")
        # 감정 표현 지침 항상 포함
        parts.append(
            "[감정 표현]\n"
            "응답 맨 앞에 감정 태그를 붙이세요: (기쁨) (슬픔) (화남) (놀람) (평온) (수줍) (기대) (진지) (걱정)\n"
            "예시: '(기대) 오, 그거 재미있겠는데요!'\n"
            "대화 맥락에 맞게 자연스럽게 선택하세요."
        )
        return "\n\n".join(parts)

    def generate(self, text: str) -> str:
        """TTS 출력 전 캐릭터 말투 적용 (실제 구현)"""
        if not self.personality:
            return text
        return self._apply_speech_style(text)
```

LLM이 `(기쁨)`, `(걱정)` 등을 직접 생성하면 기존
`parse_emotion_text()` → 캐릭터 애니메이션 → TTS 파이프라인이
추가 코드 없이 자동 연동됨.

---

### 1-4. 모델 설정 연동 + 응답 길이 동적화 + 스트리밍

**파일:** `assistant/groq_assistant.py` (수정)

```python
# 모델 하드코딩 제거
model = ConfigManager.get("llm_model") or "llama-3.3-70b-versatile"

# max_tokens 동적 조정
def _estimate_max_tokens(self, message: str) -> int:
    length = len(message)
    if length < 20:  return 200
    if length < 60:  return 400
    if length < 150: return 600
    return 800

# 스트리밍 활성화
# 청크를 문장 단위로 모아 TTS에 전달
# → 전체 응답 완료 전에 말하기 시작 → 체감 응답속도 대폭 개선
stream=True

# ⚠️ TTS 연동 주의사항:
# tts_wrapper()는 현재 동기 호출이므로 청크 단위로 직접 호출하면 안 됨.
# TTSThread는 내부적으로 큐(queue) 방식으로 동작하므로
# 문장 구분자(。.!?~\n)를 기준으로 청크를 모아 문장이 완성될 때마다
# tts_wrapper()에 한 문장씩 전달하는 방식으로 구현할 것.
# 감정 태그 (기쁨) 등은 첫 번째 청크에 포함되므로
# 첫 문장 완성 시점에 태그 파싱 후 tts_wrapper() 호출.
```

---

### 1-5. 대화 히스토리 슬라이딩 요약

**파일:** `memory/conversation_history.py` (수정)

50턴 초과 시 오래된 맥락이 사라지는 구조 교체.

```python
class ConversationHistory:
    MAX_ACTIVE = 20        # LLM에 직접 전달하는 최근 대화 수
    COMPRESS_UNIT = 5      # 한 번에 요약할 대화 수
    MAX_SUMMARIES = 5      # 보관할 요약 수

    def add(self, user_msg: str, ai_response: str):
        self.active.append({...})
        if len(self.active) > self.MAX_ACTIVE:
            self._compress_oldest()

    def _compress_oldest(self):
        to_compress = self.active[:self.COMPRESS_UNIT]
        summary = self._summarize_with_llm(to_compress)
        self.summaries.append(summary)
        if len(self.summaries) > self.MAX_SUMMARIES:
            self.summaries = self.summaries[-self.MAX_SUMMARIES:]
        self.active = self.active[self.COMPRESS_UNIT:]
        self._save()

    def get_messages_for_llm(self) -> list:
        messages = []
        if self.summaries:
            combined = " | ".join(self.summaries[-3:])
            messages.append({
                "role": "system",
                "content": f"[이전 대화 요약] {combined}"
            })
        messages.extend(self.active)
        return messages
```

---

### 1-6. API 오프라인 폴백

**파일:** `assistant/groq_assistant.py` (수정)

```python
def chat_with_tools(self, user_message, include_context=True):
    try:
        ...  # 기존 API 호출
    except (ConnectionError, TimeoutError) as e:
        logging.warning(f"API 연결 실패, 오프라인 모드: {e}")
        return self._offline_response(user_message), []

def _offline_response(self, message: str) -> str:
    # "인터넷 연결이 없어서 AI 기능이 제한돼요.
    #  볼륨, 타이머, 파일 작업은 사용 가능해요."
    return "(걱정) 인터넷 연결이 없어서 AI 기능이 제한돼요. 기본 명령은 그대로 쓸 수 있어요."
```

---

### 1-7. 응답 캐싱

**파일:** `assistant/groq_assistant.py` (수정)

```python
class ResponseCache:
    """최근 50개 응답 캐시 (TTL 10분)"""
    def get(self, message: str) -> Optional[str]
    def set(self, message: str, response: str)

# 캐싱 대상: 날씨/시간/단순 정보 질문
# 캐싱 제외: 자동화 명령, 개인화 필요 질문, tool_calls 포함 응답
```

---

## Phase 2 — 개인화 심화

---

### 2-1. UserProfileEngine — 사용자 모델 추론

**파일:** `memory/user_profile_engine.py` (신규)

```python
@dataclass
class UserProfile:
    expertise_areas: Dict[str, float]  # {"코딩": 0.9, "요리": 0.3}
    response_style: str                # "간결" | "상세" | "친근" | "격식"
    active_hours: List[int]            # 주로 활동하는 시간대
    frequent_goals: List[str]          # 자주 요청하는 작업 유형
    last_profiled: str

class UserProfileEngine:
    def update(self, user_msg: str, command_type: str, success: bool)
    def get_profile(self) -> UserProfile

    def get_prompt_injection(self) -> str:
        """
        반환 예시:
        '[사용자 정보]
        - 응답 선호: 간결하고 기술적인 설명
        - 주요 관심: 코딩, 자동화
        - 현재 시간대: 활동 시간 (저녁)'
        """
```

`groq_assistant._build_system()`에서 시스템 프롬프트 상단에 자동 삽입.

---

### 2-2. 메모리 → 프롬프트 품질 개선

**파일:** `memory/memory_manager.py` (수정)

현재 `get_full_context_prompt()`가 단순 나열.
LLM이 실제로 잘 쓸 수 있는 구조화된 형식으로 개선.

```python
def get_top_facts_prompt(self, n: int = 5) -> str:
    """신뢰도 상위 n개 fact만 구조화해서 반환"""
    top_facts = sorted(
        self.context_manager.context["facts"].items(),
        key=lambda x: x[1].get("confidence", 0),
        reverse=True
    )[:n]

    if not top_facts:
        return ""
    lines = ["[기억하고 있는 사실]"]
    for key, fact in top_facts:
        lines.append(f"- {key}: {fact['value']}")
    return "\n".join(lines)
```

---

### 2-3. MemoryIndex — FTS 전문 검색

**파일:** `memory/memory_index.py` (신규)

JSON 선형 스캔 → SQLite FTS5.
"저번에 내가 말한 거 기억해?" 같은 자연어 검색 지원.

```python
class MemoryIndex:
    # DB 경로: EXE 배포 환경(%AppData%\Ari\)과 개발 환경 분기
    # ConfigManager.get_data_dir() 또는 아래 패턴 사용:
    # import os, sys
    # _base = os.path.join(os.environ.get("APPDATA",""), "Ari") \
    #         if getattr(sys, "frozen", False) else os.path.dirname(__file__)
    DB_PATH = os.path.join(_base, "ari_memory.db")

    def index_conversation(self, user_msg: str, ai_response: str, timestamp: str)
    def index_fact(self, key: str, value: str, confidence: float)
    def search(self, query: str, limit: int = 5) -> List[MemorySearchResult]
    def search_by_date(self, start: datetime, end: datetime) -> List[MemorySearchResult]
    def rebuild_index(self)  # 기존 JSON 데이터 일괄 인덱싱
```

---

### 2-4. TrustEngine 확장

**파일:** `memory/trust_engine.py` (수정)

```python
# 배치 감쇠 — 앱 시작 시 모든 fact 한 번에 처리
def batch_decay(facts: Dict, current_time: datetime) -> Dict

# 출처 신뢰도 자동 학습
# 특정 source가 틀린 정보 자주 제공 → SOURCE_WEIGHTS 자동 하향
def update_source_weight(source: str, was_correct: bool) -> float
```

---

## Phase 3 — 로컬 LLM(Ollama) + 멀티 LLM 라우팅 + Few-shot 주입

> API 구조에서 모델 가중치 없이 낼 수 있는 최대 성능.
> 배포 환경(다양한 Windows PC)에서 동작 — 고사양 사용자는 Ollama 로컬 LLM 선택 가능.

---

### 3-0. Ollama 로컬 LLM 지원

**파일 3개 수정:** `agent/llm_provider.py`, `ui/settings_dialog.py`, `core/config_manager.py`

Ollama는 OpenAI 호환 API를 제공하므로 기존 `openai SDK + base_url` 방식 그대로 연결 가능.
코드 변경이 최소화되고, 기존 프로바이더 구조를 그대로 재사용함.

#### `agent/llm_provider.py` — `_PROVIDER_CONFIG`에 ollama 추가

```python
_PROVIDER_CONFIG = {
    # ... 기존 항목 유지 ...
    "ollama": {
        "base_url": "http://localhost:11434/v1",  # 기본값, 설정에서 변경 가능
        "default_model": "llama3.2",
        "label": "Ollama (로컬)",
        "requires_api_key": False,  # API 키 불필요
    },
}
```

`_make_client()`에 Ollama 예외 처리 추가:

```python
def _make_client(self, provider: str, api_key: str):
    cfg = _PROVIDER_CONFIG.get(provider, _PROVIDER_CONFIG["groq"])
    try:
        if provider == "anthropic":
            ...  # 기존 유지
        elif provider == "ollama":
            from openai import OpenAI
            # Ollama는 API 키 불필요 — 더미 키로 SDK 초기화
            ollama_url = self._get_ollama_url()  # 설정에서 읽음
            return OpenAI(
                api_key="ollama",  # 더미 키 (Ollama는 키 검증 안 함)
                base_url=ollama_url,
            )
        else:
            ...  # 기존 유지
    except Exception as e:
        logging.error(f"LLM 클라이언트 초기화 실패 ({provider}): {e}")
        return None

def _get_ollama_url(self) -> str:
    """설정에서 Ollama 서버 주소 읽기 (없으면 기본값)"""
    try:
        from core.config_manager import ConfigManager
        return ConfigManager.get("ollama_base_url", "http://localhost:11434/v1")
    except Exception:
        return "http://localhost:11434/v1"
```

`get_llm_provider()`의 `_KEY_MAP`에 ollama 추가:

```python
_KEY_MAP = {
    "groq": "groq_api_key",
    ...  # 기존 유지
    "ollama": "",  # API 키 없음 — 빈 문자열로 처리
}
```

`get_llm_provider()` 내 api_key 로드 시 ollama 예외 처리:

```python
provider = s.get("llm_provider", "groq")
# Ollama는 API 키 불필요
if provider == "ollama":
    api_key = "ollama"  # 더미 키
else:
    api_key = s.get(_KEY_MAP.get(provider, ""), "")
```

#### `ui/settings_dialog.py` — `_LLM_PROVIDERS` 목록에 추가

```python
_LLM_PROVIDERS = [
    ("Groq (Llama 3.3, 무료)",   "groq",       "groq_api_key",       "https://console.groq.com 에서 무료 발급"),
    ("OpenAI (GPT-4o)",          "openai",     "openai_api_key",     "https://platform.openai.com/api-keys"),
    ("Anthropic (Claude)",       "anthropic",  "anthropic_api_key",  "https://console.anthropic.com"),
    ("Mistral AI",               "mistral",    "mistral_api_key",    "https://console.mistral.ai"),
    ("Google Gemini",            "gemini",     "gemini_api_key",     "https://aistudio.google.com/app/apikey"),
    ("OpenRouter (멀티모델)",    "openrouter", "openrouter_api_key", "https://openrouter.ai/keys"),
    ("NVIDIA NIM",               "nvidia_nim", "nvidia_nim_api_key", "https://build.nvidia.com 에서 nvapi- 키 발급"),
    # ── 신규 추가 ──
    ("Ollama (로컬 LLM)",        "ollama",     "",                   "Ollama 설치 후 사용 가능 — API 키 불필요"),
]
```

Ollama 선택 시 API 키 입력란 숨기고 대신 서버 주소 + 모델 안내 표시:

```python
def _on_llm_changed(self):
    provider = self.llm_provider_combo.currentData()
    is_ollama = (provider == "ollama")

    # API 키 입력란 표시/숨김
    self.api_key_widget.setVisible(not is_ollama)

    # Ollama 전용 안내 위젯 표시/숨김
    self.ollama_hint_label.setVisible(is_ollama)
    # "Ollama가 실행 중이어야 합니다.
    #  서버 주소: http://localhost:11434 (기본값)
    #  모델명 예시: llama3.2, qwen2.5, gemma3"
```

#### `core/config_manager.py` — 기본값에 ollama 설정 추가

```python
DEFAULT_SETTINGS = {
    ...  # 기존 유지
    # ── Ollama 로컬 LLM ──
    "ollama_base_url": "http://localhost:11434/v1",
    # ollama_model은 llm_model과 공유 (별도 키 불필요)
}
```

#### Ollama 연결 테스트

기존 설정 다이얼로그의 "연결 테스트" 버튼이 Ollama에서도 동작하도록 확인.
Ollama 미실행 시 명확한 오류 메시지 제공:

```python
# 연결 실패 시
"Ollama 서버에 연결할 수 없어요.\n"
"Ollama가 설치되어 있고 실행 중인지 확인하세요.\n"
"설치: https://ollama.com"
```

#### Ollama 사용자 가이드 (README/설정 UI 안내문)

```
Ollama 로컬 LLM 사용법:
1. https://ollama.com 에서 Ollama 설치
2. 터미널에서 원하는 모델 다운로드:
   ollama pull llama3.2        (4GB, 범용)
   ollama pull qwen2.5         (5GB, 한국어 강함)
   ollama pull gemma3          (5GB, 경량)
   ollama pull qwen2.5:14b     (9GB, 고성능)
3. Ari 설정 → LLM 제공자 → "Ollama (로컬 LLM)" 선택
4. 모델명 입력 (예: llama3.2)
5. 연결 테스트

권장 사양: RAM 8GB 이상, 모델에 따라 VRAM 필요
장점: 인터넷 불필요, 응답 빠름, API 비용 없음, 개인정보 보호
단점: 초기 모델 다운로드 필요 (4~10GB), 저사양 PC에서 느림
```

---

### 3-1. 멀티 LLM 라우팅

**파일:** `agent/llm_router.py` (신규)

작업 유형에 따라 최적 모델 자동 선택.
`llm_provider.py`의 플래너/실행 분리를 대화 레이어까지 확장.

```python
class LLMRouter:
    ROUTE_TABLE = {
        "simple_chat":   {"provider": "groq",   "model": "llama-3.3-70b-versatile"},
        "complex_plan":  {"provider": "groq",   "model": "llama-3.3-70b-versatile"},
        "code_gen":      {"provider": "groq",   "model": "qwen-qwq-32b"},  # 추론 특화
        "long_analysis": {"provider": "openai", "model": "gpt-4o-mini"},
        "offline":       {"provider": "edge",   "model": None},
    }

    def route(self, message: str, context: dict) -> RouteResult:
        task_type = self._classify_task(message)
        # API 키 있는 프로바이더만 선택, 없으면 자동 폴백
        return self._select_available(self.ROUTE_TABLE[task_type])

    def _classify_task(self, message: str) -> str:
        """LLM 호출 없이 규칙 기반으로 빠르게 분류"""
        if len(message) < 20 and not any(kw in message for kw in COMPLEX_KEYWORDS):
            return "simple_chat"
        if any(kw in message for kw in CODE_KEYWORDS):
            return "code_gen"
        if any(kw in message for kw in PLAN_KEYWORDS):
            return "complex_plan"
        return "simple_chat"
```

`ari_settings.json`에 라우팅 테이블 커스터마이즈 가능.
사용자가 API 키를 넣은 프로바이더만 활성화됨.

---

### 3-2. Few-shot 자동 주입

**파일:** `agent/few_shot_injector.py` (신규)

StrategyMemory 성공 사례를 LLM 프롬프트 예시로 자동 삽입.
모델 가중치를 못 건드리는 API 구조에서 가장 효과적인 성능 향상 방법.
사용할수록 그 사람의 패턴에 맞게 정확도가 올라감.

```python
class FewShotInjector:
    MAX_EXAMPLES = 3  # 토큰 절약을 위해 최대 3개

    def get_examples(self, goal: str) -> str:
        """현재 목표와 유사한 성공 사례 → 예시 형식으로 변환"""
        similar = strategy_memory.search_similar_records(goal, limit=self.MAX_EXAMPLES)
        successful = [r for r in similar if r.success and r.steps_desc]

        if not successful:
            return ""

        lines = ["[유사 작업 성공 사례]"]
        for rec in successful:
            lines.append(f"목표: {rec.goal_summary[:80]}")
            lines.append(f"접근: {' → '.join(rec.steps_desc[:3])}")
            if rec.lesson:
                lines.append(f"주의: {rec.lesson[:100]}")
            lines.append("")
        return "\n".join(lines)
```

`agent_planner.decompose()` 호출 시 플래너 프롬프트에 자동 삽입.

---

### 3-3. PlannerFeedbackLoop — 플래너 자동 튜닝

**파일:** `agent/planner_feedback.py` (신규)

어떤 step_type 조합이 잘 되는지 플래너가 스스로 학습.

```python
class PlannerFeedbackLoop:
    def record(self, steps: List[ActionStep], success: bool, duration_ms: int)

    def get_hints(self, goal: str, tags: List[str]) -> str:
        """
        반환 예시:
        '파일 작업: python 단계 성공률 92%.
         shell 단계 권한 오류 빈발(38%) → python 대체 권장.'
        """
```

`agent_planner.decompose()` 프롬프트에 자동 주입.  
**저장:** `agent/planner_stats.json`

---

## Phase 4 — PC 자동화 고도화

---

### 4-1. SkillLibrary — 반복 작업 스킬 자동화

**파일:** `agent/skill_library.py` (신규)

성공한 자동화 패턴을 재사용 가능한 스킬로 자동 추출.
반복 요청 시 LLM 계획 없이 검증된 스텝 바로 실행.

```python
@dataclass
class Skill:
    skill_id: str
    name: str
    trigger_patterns: List[str]
    steps: List[ActionStep]      # 검증된 실행 단계
    success_count: int
    fail_count: int
    avg_duration_ms: int
    confidence: float

class SkillLibrary:
    # 동일 태그 3회 이상 성공 + 5단계 이하 → 자동 스킬 생성
    def try_extract_skill(self, goal: str, steps: list, success: bool) -> Optional[Skill]
    def get_applicable_skill(self, goal: str) -> Optional[Skill]
    # 연속 실패 2회 → 자동 비활성화
    def deprecate_if_failing(self, skill_id: str)
    def list_skills(self) -> List[Skill]
```

**`AgentOrchestrator.run()` 연동:**
```python
def run(self, goal: str) -> AgentRunResult:
    skill = skill_library.get_applicable_skill(goal)
    if skill:
        return self._run_with_skill(skill, goal)
    return self._run_loop(goal)  # 기존 Plan-Execute-Verify
```

---

### 4-2. ReflectionEngine — 구조화된 자기반성

**파일:** `agent/reflection_engine.py` (신규)

현재 단순 lesson 문자열. 구조화된 4레이어 반성으로 교체.

```python
@dataclass
class ReflectionResult:
    lesson: str
    root_cause: str              # "timeout" | "permission" | "logic_error" | ...
    avoid_patterns: List[str]    # 다음 계획에서 피할 패턴
    fix_suggestion: str

class ReflectionEngine:
    def reflect(self, goal: str, run_result: AgentRunResult) -> ReflectionResult:
        # L1: 오류 메시지 → classify_failure_message() (기존 활용)
        # L2: 실패 단계 시퀀스 → 구조적 원인 추출
        # L3: LLM 호출 → 교훈 + 수정 제안
        # L4: StrategyMemory 유사 실패 → 반복 실수 감지 경고
```

**`_post_run_update()` 신규 추가:**
```python
def _post_run_update(self, goal, run_result, duration_ms):
    if run_result.achieved:
        skill_library.try_extract_skill(...)
        few_shot_injector.add_example(...)   # Few-shot 풀 업데이트
    else:
        reflection = reflection_engine.reflect(goal, run_result)
        # avoid_patterns → 다음 planner 프롬프트에 주입
    strategy_memory.record(..., lesson=reflection.lesson)
```

---

### 4-3. 사용자 피드백 루프

**파일:** `agent/agent_orchestrator.py` (수정)

```python
def _request_feedback(self, goal: str, result: AgentRunResult):
    if not result.achieved:
        return

    # TTS: "완료했어요! 잘 됐나요?"
    # "응" → SkillLibrary 신뢰도 상승 + Few-shot 예시 품질 상승
    # "아니" → ReflectionEngine 트리거 + 스킬 신뢰도 하락
```

---

## Phase 5 — 자기개선 루프 완성

---

### 5-1. StrategyMemory 고도화

**파일:** `agent/strategy_memory.py` (수정)

```python
@dataclass
class StrategyRecord:
    ...                              # 기존 유지
    skill_id: str = ""               # 적용된 스킬 ID
    user_feedback: str = ""          # "positive" | "negative" | ""
    few_shot_eligible: bool = False  # Few-shot 예시로 쓸 수 있는 품질인지

def _prune(self):
    # 단순 FIFO → 중요도 기반
    # 보존: 성공 + 피드백 긍정 + few_shot_eligible
    # 삭제: 교훈 없는 단순 실패 + 오래됨

def generate_weekly_summary(self) -> str:
    # 주간 성공/실패 통계 + 신규 스킬 목록
```

---

### 5-2. MemoryConsolidator — 주기적 정리

**파일:** `memory/memory_consolidator.py` (신규)

```python
class MemoryConsolidator:
    def consolidate_facts(self):
        # TrustEngine.should_remove() 기준 저신뢰 fact 정리
        # 임베딩 유사도 0.9+ 중복 fact 병합

    def consolidate_strategies(self):
        # 성공 패턴 → SkillLibrary 승격
        # few_shot_eligible 체크 → FewShotInjector 풀 업데이트
        # 교훈 없는 오래된 실패 기록 정리

    def summarize_old_conversations(self, days_ago: int = 14):
        # 14일 이상 대화 LLM 요약 압축

    # ProactiveScheduler에 매일 새벽 3시 등록
    # PC가 꺼져 있었다면 다음 실행 시 자동으로 보충 실행됨 (아래 참고)
```

---

### 5-3. 주간 자기개선 리포트

**파일:** `agent/weekly_report.py` (신규)

`ProactiveScheduler`에 매주 월요일 오전 9시로 등록.
PC가 꺼져 있었다면 다음 실행 시 자동으로 보충 실행됨 (아래 5-4 참고).

---

### 5-4. PC 꺼짐 대응 — 놓친 작업 보충 실행

**파일:** `agent/proactive_scheduler.py` (수정)

현재 스케줄러는 앱 실행 중에만 30초마다 tick하는 구조라
PC가 꺼져 있던 시간에 예약된 작업은 그냥 건너뜀.
핵심 기능에는 영향 없지만, 메모리 정리/리포트 등이 누락될 수 있음.

앱 시작 시 `last_run` 필드를 체크해 놓친 작업을 자동으로 보충 실행.

```python
def check_missed_tasks_on_startup(self):
    """앱 시작 시 PC 꺼짐으로 놓친 작업 감지 및 보충 실행"""
    now = datetime.now()
    for task in self._tasks.values():
        if not task.enabled or not task.last_run:
            continue

        last = datetime.fromisoformat(task.last_run)
        elapsed = (now - last).total_seconds()

        # 작업 유형별 보충 기준
        # - 매일 작업 (MemoryConsolidator): 24시간 이상 경과 시
        # - 매주 작업 (WeeklyReport): 7일 이상 경과 시
        threshold = {
            "daily":  86400,       # 24시간
            "weekly": 86400 * 7,   # 7일
        }.get(task.repeat_rule, 86400)

        if elapsed > threshold:
            logging.info(
                f"[Scheduler] 놓친 작업 보충 실행: {task.goal} "
                f"(마지막 실행: {last.strftime('%Y-%m-%d %H:%M')})"
            )
            # 백그라운드 스레드로 실행 — 앱 시작 블로킹 방지
            threading.Thread(
                target=self._run_task,
                args=(task,),
                daemon=True,
                name=f"MissedTask-{task.task_id}"
            ).start()

# Main.py에서 앱 시작 직후 호출
# scheduler.check_missed_tasks_on_startup()
```

**동작 예시:**
- 어젯밤 새벽 3시 메모리 정리 예약 → PC 꺼져 있었음
- 오늘 오전 Ari 실행 → `check_missed_tasks_on_startup()` 호출
- 24시간 이상 경과 감지 → 백그라운드에서 메모리 정리 즉시 실행
- Ari: "(진지) 어젯밤에 못 한 메모리 정리를 지금 할게요."

**`Main.py` 연동:**
```python
def main():
    ...
    ari_core = AriCore()
    # 앱 초기화 완료 후 놓친 작업 체크
    scheduler = get_scheduler()
    scheduler.check_missed_tasks_on_startup()
    ...
```

```
[자동 TTS + 말풍선]
"이번 주 리포트예요!
 완료한 작업 23건, 성공률 87%.
 새로 배운 스킬: 파일 정리 자동화, 유튜브 재생.
 자주 실패한 작업: 복잡한 웹 로그인.
 기억하고 있는 사실: 142개."
```

---

### 5-5. 음성 메모리 명령

**파일:** `commands/memory_command.py` (신규)

```
"내가 자주 하는 작업 뭐야?"     → UserProfile.frequent_goals TTS 출력
"저번에 내가 뭐라고 했어?"       → MemoryIndex FTS 검색 결과 TTS
"내 스킬 목록 보여줘"            → SkillLibrary.list_skills() TTS
"이 스킬 삭제해줘"               → SkillLibrary.deprecate_skill()
"메모리 정리해줘"                → MemoryConsolidator 즉시 실행
"나에 대해 뭐 알아?"             → UserProfile + facts 요약 TTS
```

---

## 파일 변경 요약

### 신규 생성 (10개)

| 파일 | 역할 |
|------|------|
| `agent/llm_router.py` | 작업 유형별 최적 모델 자동 라우팅 |
| `agent/few_shot_injector.py` | StrategyMemory 성공 사례 → 프롬프트 예시 자동 삽입 |
| `agent/skill_library.py` | 성공 패턴 스킬 자동 추출/관리 |
| `agent/reflection_engine.py` | 구조화된 4레이어 자기반성 |
| `agent/planner_feedback.py` | 플래너 성능 자동 학습 |
| `agent/weekly_report.py` | 주간 자기개선 리포트 |
| `memory/memory_index.py` | SQLite FTS5 전문 검색 |
| `memory/user_profile_engine.py` | 사용자 모델 종합 추론 |
| `memory/memory_consolidator.py` | 주기적 메모리 정리/압축 |
| `commands/memory_command.py` | 메모리 관련 음성 명령 |

### 수정 (13개)

| 파일 | 핵심 변경 |
|------|-----------|
| `assistant/groq_assistant.py` | 한국어 필터 버그 수정, `include_context=True`, 모델 설정 연동, `max_tokens` 동적화, 스트리밍, 오프라인 폴백, 응답 캐싱 |
| `core/rp_generator.py` | `build_system_prompt()` 실제 구현, 말투 변환 구현 |
| `memory/conversation_history.py` | 슬라이딩 요약 방식으로 교체 |
| `memory/memory_manager.py` | 구조화된 컨텍스트 프롬프트, UserProfileEngine 연동 |
| `memory/trust_engine.py` | 배치 감쇠, 출처 신뢰도 자동 학습 |
| `agent/agent_orchestrator.py` | `_post_run_update()`, 피드백 루프, SkillLibrary/ReflectionEngine 연동 |
| `agent/strategy_memory.py` | 중요도 기반 prune, 피드백/few_shot 필드 |
| `agent/proactive_scheduler.py` | `check_missed_tasks_on_startup()` 추가 |
| `Main.py` | 앱 시작 후 `check_missed_tasks_on_startup()` 호출 |
| `agent/agent_planner.py` | FewShotInjector + PlannerFeedbackLoop 힌트 주입 |
| `agent/llm_provider.py` | Ollama 추가(`_PROVIDER_CONFIG`, `_make_client`, `_KEY_MAP`, `get_llm_provider`), LLMRouter 연동 |
| `ui/settings_dialog.py` | `_LLM_PROVIDERS`에 Ollama 추가, 선택 시 API 키란 숨김/서버 주소 안내 표시 |
| `core/config_manager.py` | `ollama_base_url` 기본값 추가 |

---

## Codex 구현 순서

```
# Phase 1 — 버그 수정 + 대화 품질 (체감 가장 큼, 먼저 시작)
1.  groq_assistant.py — 한국어 필터 버그 수정 (_clean_response로 교체)
2.  groq_assistant.py — include_context=True, 모델 설정 연동, max_tokens 동적화
3.  rp_generator.py  — build_system_prompt() + 말투 변환 실제 구현
4.  groq_assistant.py — 스트리밍 활성화 (stream=True + 청크 처리)
5.  groq_assistant.py — 오프라인 폴백 (_offline_response)
6.  groq_assistant.py — 응답 캐싱 (ResponseCache)
7.  conversation_history.py — 슬라이딩 요약 방식으로 교체

# Phase 2 — 개인화
8.  memory/user_profile_engine.py — 신규 생성
9.  memory/memory_manager.py — 구조화된 컨텍스트 프롬프트 + UserProfileEngine 연동
10. memory/memory_index.py — SQLite FTS5 신규 생성
11. memory/trust_engine.py — 배치 감쇠, 출처 신뢰도 학습

# Phase 3 — Ollama + 멀티 LLM 라우팅 + Few-shot
12. agent/llm_provider.py — _PROVIDER_CONFIG ollama 추가, _make_client Ollama 분기, _KEY_MAP 추가
13. ui/settings_dialog.py — _LLM_PROVIDERS에 Ollama 추가, API 키란 숨김/안내 UI
14. core/config_manager.py — ollama_base_url 기본값 추가
15. agent/llm_router.py — 신규 생성 (Ollama 포함 라우팅 테이블)
16. agent/few_shot_injector.py — 신규 생성
17. agent/agent_planner.py — FewShotInjector + PlannerFeedbackLoop 연동
18. agent/planner_feedback.py — 신규 생성

# Phase 4 — 자동화 고도화
19. agent/skill_library.py — 신규 생성
20. agent/reflection_engine.py — 신규 생성
21. agent/agent_orchestrator.py — _post_run_update(), 피드백 루프

# Phase 5 — 자기개선 루프 완성
22. agent/strategy_memory.py — 중요도 prune, few_shot 필드
23. memory/memory_consolidator.py — 신규 생성
24. agent/proactive_scheduler.py — check_missed_tasks_on_startup() 추가
25. Main.py — 앱 시작 후 check_missed_tasks_on_startup() 호출
26. agent/weekly_report.py — 신규 생성
27. commands/memory_command.py — 신규 생성
```

---

## Claude Code 검증 체크리스트

### Phase 1
- [ ] `_filter_korean_text` 제거 후 URL/영문 포함 응답 정상 출력
- [ ] `include_context=True` 후 실제 LLM 요청에 컨텍스트 포함 확인
- [ ] `rp_generator.build_system_prompt()` 결과가 시스템 프롬프트에 반영
- [ ] LLM 응답에 감정 태그 자동 생성 → 캐릭터 애니메이션 연동
- [ ] 설정에서 모델 변경 시 실제 API 호출에 반영
- [ ] 스트리밍 응답 — 첫 문장 완성 시 TTS 즉시 시작
- [ ] API 오프라인 시 `_offline_response` 반환 (에러 메시지 아님)
- [ ] 동일 질문 2회 → 캐시 히트 확인 (API 호출 1회만)
- [ ] 대화 20턴 초과 시 슬라이딩 요약 압축 동작

### Phase 2
- [ ] `UserProfileEngine` 10회 대화 후 프로파일 변화 확인
- [ ] 시스템 프롬프트 상단에 UserProfile 주입 확인
- [ ] FTS 검색 "저번에 내가 말한 거" 동작
- [ ] `batch_decay()` 앱 시작 시 자동 실행

### Phase 3
- [ ] Ollama 선택 시 API 키 입력란 숨김, 서버 주소 안내 표시
- [ ] Ollama 연결 테스트 버튼 동작 (실행 중/미실행 각각 확인)
- [ ] Ollama 미실행 시 명확한 오류 메시지 (`_offline_response` 연동)
- [ ] `LLMRouter` — 짧은 명령/복잡한 계획/코드 생성 각각 다른 모델 선택
- [ ] Ollama 프로바이더 선택 시 LLMRouter가 ollama로 라우팅
- [ ] API 키 없는 프로바이더로 라우팅 시 자동 폴백
- [ ] `FewShotInjector` — 유사 성공 사례 플래너 프롬프트에 주입 확인
- [ ] `PlannerFeedbackLoop` 힌트가 플래너 프롬프트에 포함

### Phase 4
- [ ] `SkillLibrary` — 동일 유형 3회 성공 후 스킬 자동 생성
- [ ] 스킬 적용 시 기존 Plan-Execute보다 빠른 실행
- [ ] `ReflectionEngine` — 실패 시 `ReflectionResult` 4필드 모두 채워짐
- [ ] 사용자 "아니" 피드백 → 스킬 신뢰도 하락 확인

### Phase 5
- [ ] `StrategyMemory` prune — 성공+긍정피드백 기록이 단순 실패보다 우선 보존
- [ ] `MemoryConsolidator` 실행 중 다른 기능 블로킹 없음 (별도 스레드)
- [ ] 주간 리포트 — `ProactiveScheduler` 월요일 9시 등록 확인
- [ ] `check_missed_tasks_on_startup()` — 24시간 이상 경과한 작업 앱 시작 시 자동 보충 실행
- [ ] 보충 실행이 백그라운드 스레드로 처리되어 앱 시작 블로킹 없음
- [ ] 음성 명령 6종 전부 동작

### 기존 테스트 회귀
- [ ] `tests/test_strategy_memory.py` 전부 통과
- [ ] `tests/test_user_context.py` 전부 통과
- [ ] `tests/test_safety_checker.py` 전부 통과
- [ ] `tests/test_tts_factory.py` 전부 통과
- [ ] `tests/test_plugin_loader.py` 전부 통과

---

## API 구조 한계 vs 달성 가능한 것

| 항목 | Hermes RL | Ari 이 계획 | 비고 |
|------|-----------|-------------|------|
| 모델 가중치 개선 | ✅ | ❌ | API 구조 근본 한계 |
| 로컬 LLM 지원 | ✅ | ✅ Ollama | 고사양 사용자 선택 가능 |
| 프롬프트 기반 학습 | 부분 | ✅ Few-shot | 실질 효과 큼 |
| 작업별 최적 모델 | ✅ | ✅ LLMRouter | 동등 |
| 개인화 깊이 | 일반적 | ✅ 1인 특화 | Ari 우위 |
| 반복 작업 자동화 | ✅ | ✅ SkillLibrary | 동등 |
| 자기반성 구조 | ✅ | ✅ ReflectionEngine | 동등 |
| 음성 + 캐릭터 UI | ❌ | ✅ | Ari 독점 강점 |
| 배포 용이성 | 서버 필요 | ✅ 일반 PC | Ari 우위 |
| 오프라인 동작 | 부분 | ✅ Ollama + Edge TTS | Ari 우위 |

---

## 완성 후 Ari가 할 수 있는 것

```
[대화 품질]
사용자: "저번에 추천해준 영화 기억해?"
Ari:    "(기대) 네! 지난 화요일에 SF 영화 얘기 하셨잖아요.
         인터스텔라 말씀드렸는데 보셨어요?"

[개인화]
Ari:    "(진지) 오후 11시네요. 주로 이 시간에 코딩 작업 하시더라고요.
         오늘도 개발 관련 도움 필요하신 거 있어요?"

[자동화 — 스킬 재사용]
사용자: "바탕화면 파일 정리해줘"
Ari:    "(기쁨) 이 작업은 전에 배웠어요! 바로 할게요."
        → SkillLibrary 검증된 스텝 즉시 실행 (LLM 계획 없이)

[Few-shot 효과]
사용자: (처음 보는 복잡한 작업 요청)
Ari:    → 유사 성공 사례 참고해 처음부터 올바른 접근 선택

[월요일 오전 9시 자동]
Ari:    "이번 주 리포트예요! 완료한 작업 18건, 성공률 89%.
         새로 배운 스킬 2개, 기억하는 사실 156개예요."

[오프라인 — Ollama 사용자]
사용자: (인터넷 끊긴 상태에서 말 걸기)
Ari:    "(평온) 인터넷이 없어도 괜찮아요. 로컬 AI로 대화할게요!"
        → Ollama 로컬 모델이 응답 (API 불필요)

[오프라인 — API 전용 사용자]
사용자: (인터넷 끊긴 상태에서 말 걸기)
Ari:    "(걱정) 인터넷 연결이 없어서 AI 기능이 제한돼요.
         볼륨 조절, 타이머, 파일 작업은 그래도 할 수 있어요!"
```
