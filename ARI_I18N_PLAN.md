# Ari i18n 국제화 계획

> v4 Full Plan 완료 후 적용
> 구현: Codex / 검증: Claude Code
> 지원 언어: 한국어(ko), 영어(en), 일본어(ja)

---

## 1. 설계 방침

### 방법론: `gettext` 기반

| 항목 | JSON | gettext |
|------|------|---------|
| Python 표준 라이브러리 | ❌ 별도 구현 | ✅ 내장 |
| 변수 보간 | 직접 구현 | `_("주의: {msg}", msg=x)` |
| 복수형 처리 | 직접 구현 | `ngettext()` 내장 |
| 문자열 자동 추출 | 없음 | `xgettext` 자동 추출 |

### 적용 대상 / 제외 대상

**적용 대상:**
- UI 레이블, 버튼, 창 제목, 트레이 메뉴 (`ui/`)
- TTS 발화 문자열 (`agent/`, `core/`, `commands/`)
- 말풍선, 상태 메시지, 오류 메시지 (사용자에게 보이는 것)
- `agent_planner.py` 플래너 프롬프트 — 한국어/영어 분기, 일본어는 영어 프롬프트 사용
- LLM 동적 생성 결과물 (`summary_kr` 등) — 시스템 프롬프트 언어 주입으로 처리
- `safety_checker.py` `summary_kr` 하드코딩 문자열

**제외 대상:**
- `logging.*()` 로그 메시지 — **영어 고정** (버그 리포트 시 언어 무관하게 개발자가 읽을 수 있어야 함. 같은 로그 파일에 여러 언어 섞이면 추적 불가)
- 사용자가 설정에서 직접 작성하는 `system_prompt`, `personality`
- 파일 경로, URL, API 키 관련 문자열

**로그 접근성 보완:** 설정 UI에 "로그 파일 폴더 열기" 버튼 추가.

### 핵심 구현 원칙

**`_()` 는 반드시 함수/메서드 내부에서만 호출.**
모듈 레벨 상수에 `_()` 사용 시 `i18n_init()` 이전에 평가되어 번역 미적용.
클래스 변수, 모듈 상수에는 사용 금지.

---

## 2. 디렉터리 구조

```
VoiceCommand/
  i18n/
    __init__.py
    translator.py
    locales/
      ko/LC_MESSAGES/ari.po, ari.mo
      en/LC_MESSAGES/ari.po, ari.mo
      ja/LC_MESSAGES/ari.po, ari.mo
  scripts/
    extract_strings.py   # _() 문자열 자동 추출
    compile_po.py        # .po → .mo 컴파일
```

---

## 3. 핵심 구현

### 3-1. `i18n/translator.py`

```python
"""
Ari 국제화(i18n) 번역 엔진.

사용법:
    from i18n.translator import _, ngettext, set_language, get_language

    _("설정")
    _("주의: {msg}", msg=report.text)
    ngettext("{n}개 파일", "{n}개 파일들", n, n=n)

주의: _()는 반드시 함수/메서드 내부에서만 호출할 것.
      모듈 레벨 상수에 사용하면 init() 전에 평가되어 번역 미적용.
"""
from __future__ import annotations

import builtins
import gettext
import logging
import os
import threading
from typing import Optional

_LOCALE_DIR = os.path.join(os.path.dirname(__file__), "locales")
_DOMAIN = "ari"
_DEFAULT_LANG = "ko"
_SUPPORTED = {"ko", "en", "ja"}

_current_lang: str = _DEFAULT_LANG
_translation: Optional[gettext.GNUTranslations] = None
_lock = threading.RLock()

logger = logging.getLogger(__name__)


def _load(lang: str) -> gettext.GNUTranslations:
    try:
        return gettext.translation(_DOMAIN, localedir=_LOCALE_DIR, languages=[lang])
    except FileNotFoundError:
        logger.warning("[i18n] '%s' translation not found, using fallback", lang)
        return gettext.NullTranslations()


def init(lang: Optional[str] = None) -> None:
    """앱 시작 시 한 번 호출. lang이 None이면 settings에서 읽음."""
    global _current_lang, _translation
    if lang is None:
        try:
            from core.config_manager import ConfigManager
            lang = ConfigManager.get("language", _DEFAULT_LANG)
        except Exception:
            lang = _DEFAULT_LANG

    lang = lang if lang in _SUPPORTED else _DEFAULT_LANG

    with _lock:
        _current_lang = lang
        _translation = _load(lang)
        _translation.install()
        builtins.__dict__["_"] = gettext_func
        builtins.__dict__["ngettext"] = ngettext_func

    logger.info("[i18n] Language set: %s", lang)


def set_language(lang: str) -> None:
    """런타임 언어 전환. UI 반영은 재시작 필요."""
    if lang not in _SUPPORTED:
        logger.warning("[i18n] Unsupported language: %s", lang)
        return
    global _current_lang, _translation
    with _lock:
        _current_lang = lang
        _translation = _load(lang)
        _translation.install()
        builtins.__dict__["_"] = gettext_func
        builtins.__dict__["ngettext"] = ngettext_func
    logger.info("[i18n] Language changed: %s", lang)


def get_language() -> str:
    return _current_lang


def gettext_func(message: str, **kwargs) -> str:
    with _lock:
        t = _translation or gettext.NullTranslations()
    translated = t.gettext(message)
    return translated.format(**kwargs) if kwargs else translated


def ngettext_func(singular: str, plural: str, n: int, **kwargs) -> str:
    with _lock:
        t = _translation or gettext.NullTranslations()
    translated = t.ngettext(singular, plural, n)
    return translated.format(n=n, **kwargs) if kwargs else translated


_ = gettext_func
ngettext = ngettext_func
```

### 3-2. `i18n/__init__.py`

```python
from i18n.translator import init, set_language, get_language, _, ngettext
__all__ = ["init", "set_language", "get_language", "_", "ngettext"]
```

### 3-3. `Main.py` 초기화

```python
# Main.py — 다른 모든 import 전에 최상단에 위치해야 함
# UI/agent 모듈이 임포트되기 전에 번역 엔진을 초기화해야
# 모듈 레벨 _() 호출 시 번역이 적용됨
import sys
import os
import logging

# ↓ 반드시 PySide6, ui, agent 등 import 전에 위치
from i18n import init as i18n_init
i18n_init()

# 이후 기존 import
from PySide6.QtWidgets import QApplication, ...
from ui.character_widget import CharacterWidget
...
```

---

## 4. `_TOOL_INSTRUCTION` 함수화

**현재 문제:** `_TOOL_INSTRUCTION`이 모듈 레벨 상수로 한국어 하드코딩.
영어/일본어 모드에서도 LLM에게 "한국어로 답변하라"고 지시하게 됨.

```python
# 현재 (문제)
_TOOL_INSTRUCTION = (
    "[도구 사용 지침]\n"
    "- 답변은 한국어로 하되, ..."
)

# 수정 — 함수로 변경
def _get_tool_instruction() -> str:
    from i18n.translator import get_language
    lang = get_language()
    if lang == "en":
        return (
            "[Tool Usage Guidelines]\n"
            "- Always respond in English.\n"
            "- Use appropriate tools for PC control requests.\n"
            "- Do not damage URLs, code, or English names in responses."
        )
    if lang == "ja":
        return (
            "[ツール使用ガイドライン]\n"
            "- 常に日本語で回答してください。\n"
            "- PC操作の要求には適切なツールを使用してください。\n"
            "- URL・コード・英語の名称は変更しないでください。"
        )
    return (
        "[도구 사용 지침]\n"
        "- 사용자의 PC 동작 요청은 적절한 도구를 우선 호출하세요.\n"
        "- 위험하거나 파괴적인 작업은 명확한 의도를 확인하세요.\n"
        "- 답변은 한국어로 하되, URL/코드/영문 명칭은 손상시키지 마세요."
    )
```

`_build_system()` 내에서 `_TOOL_INSTRUCTION` → `_get_tool_instruction()` 으로 교체.

---

## 5. `_build_system()` 언어 주입

```python
# agent/llm_provider.py
def _build_system(self, include_context: bool = False) -> str:
    from i18n.translator import get_language
    lang = get_language()

    # 언어별 base_prompt (사용자 설정 system_prompt 우선)
    _BASE_PROMPT = {
        "ko": "당신은 한국어 AI 어시스턴트 아리입니다.",
        "en": "You are Ari, an AI assistant.",
        "ja": "あなたはAIアシスタントのAriです。",
    }
    base_prompt = self.system_prompt or _BASE_PROMPT.get(lang, _BASE_PROMPT["ko"])

    # 언어 지시 (마지막에 추가 — LLM이 가장 주의 깊게 읽음)
    _LANG_INSTRUCTION = {
        "ko": "항상 한국어로 응답하세요.",
        "en": "Always respond in English.",
        "ja": "常に日本語で応答してください。",
    }
    lang_instruction = _LANG_INSTRUCTION.get(lang, _LANG_INSTRUCTION["ko"])

    parts: List[str] = []
    # ... 기존 context 주입 로직 유지 ...
    parts.append(self.rp_generator.build_system_prompt(base_prompt))
    parts.append(_get_tool_instruction())
    parts.append(lang_instruction)   # 기존 하드코딩 줄 교체
    return "\n\n".join(part for part in parts if part)
```

---

## 6. `rp_generator.py` 감정 태그 언어 분기

**현재 문제:** 감정 태그가 한국어 고정. 영어 사용자에게 `(기쁨)` 표시됨.

```python
# core/rp_generator.py build_system_prompt()
def build_system_prompt(self, base_prompt: str) -> str:
    from i18n.translator import get_language
    lang = get_language()

    _EMOTION_INSTRUCTION = {
        "ko": (
            "[감정 표현]\n"
            "응답 맨 앞에 감정 태그를 자연스럽게 붙이세요. "
            "예: (기쁨) (슬픔) (화남) (놀람) (평온) (수줍) (기대) (진지) (걱정)"
        ),
        "en": (
            "[Emotion Tags]\n"
            "Start your response with an emotion tag naturally. "
            "Examples: (joy) (sad) (angry) (surprised) (calm) (shy) (excited) (serious) (worried)"
        ),
        "ja": (
            "[感情タグ]\n"
            "返答の先頭に感情タグを自然につけてください。"
            "例: (喜び) (悲しみ) (怒り) (驚き) (穏やか) (恥ずかしい) (期待) (真剣) (心配)"
        ),
    }
    emotion_instruction = _EMOTION_INSTRUCTION.get(lang, _EMOTION_INSTRUCTION["ko"])

    parts = [base_prompt.strip() or _BASE_PROMPT.get(lang, _BASE_PROMPT["ko"])]
    if self.personality:
        parts.append(f"[캐릭터 성격]\n{self.personality.strip()}")
    if self.scenario:
        parts.append(f"[현재 상황]\n{self.scenario.strip()}")
    if self.history_instruction:
        parts.append(f"[대화 방식]\n{self.history_instruction.strip()}")
    parts.append(emotion_instruction)
    return "\n\n".join(part for part in parts if part)
```

---

## 7. `agent_planner.py` 프롬프트 언어 분기

**플래너 프롬프트 수:** `_DECOMPOSE_PROMPT`, `_DEVELOPER_DECOMPOSE_PROMPT`,
`_DEVELOPER_RETRY_PROMPT`, `_FIX_PROMPT`, `_VERIFY_PROMPT`, `_REFLECT_PROMPT` — 6개.

3개 언어 × 6개 = 18벌 관리는 유지보수 부담이 큼.

**현실적 전략:**
- 한국어/영어 2벌만 작성
- 일본어는 영어 프롬프트 사용 + `lang_instruction`으로 일본어 응답 유도
- 대부분의 LLM이 영어 지시를 더 안정적으로 따름

```python
# agent_planner.py
def _get_decompose_prompt() -> str:
    from i18n.translator import get_language
    lang = get_language()
    if lang == "en" or lang == "ja":  # 일본어도 영어 프롬프트 사용
        return _DECOMPOSE_PROMPT_EN
    return _DECOMPOSE_PROMPT_KO

_DECOMPOSE_PROMPT_KO = """\
다음 목표를 달성하기 위한 실행 단계를 JSON 배열로 반환하세요.
목표: {goal}
{context_block}
규칙:
- step_type: "python" | "shell" | "think"
- 단순한 작업은 1단계로 충분합니다
- 코드는 즉시 실행 가능하게 작성하세요
..."""

_DECOMPOSE_PROMPT_EN = """\
Return an execution plan as a JSON array to achieve the following goal.
Goal: {goal}
{context_block}
Rules:
- step_type: "python" | "shell" | "think"
- Simple tasks need only one step
- Write immediately executable code
..."""

# _FIX_PROMPT, _VERIFY_PROMPT 등 나머지도 동일 패턴 적용
```

---

## 8. `safety_checker.py` 다국어 처리

```python
from i18n.translator import _

# 변경 전
summary_kr = f"위험한 파이썬 작업 감지: {', '.join(matched)}"

# 변경 후 — summary_kr → summary 필드명 변경
summary = _("위험한 파이썬 작업 감지: {matched}", matched=", ".join(matched))
```

**`summary_kr` → `summary` 필드명 변경 주의:**
80곳에서 참조 중. 누락 시 `AttributeError`로 앱이 중단됨.
변경 후 반드시 `validate_repo.py` + 전체 테스트 실행.

---

## 9. TTS 음성 자동 전환

```python
# settings_schema.py
_TTS_VOICE_BY_LANG = {
    "ko": "ko-KR-SunHiNeural",
    "en": "en-US-JennyNeural",
    "ja": "ja-JP-NanamiNeural",
}

def get_default_edge_tts_voice() -> str:
    from i18n.translator import get_language
    return _TTS_VOICE_BY_LANG.get(get_language(), "ko-KR-SunHiNeural")
```

사용자가 설정에서 음성을 직접 지정한 경우 해당 설정 우선.

---

## 10. 번역 카탈로그

### `ko/LC_MESSAGES/ari.po`

```po
# Ari Voice Assistant — 한국어
msgid ""
msgstr ""
"Content-Type: text/plain; charset=UTF-8\n"
"Language: ko\n"

msgid "아리 설정"
msgstr "아리 설정"

msgid "마이크 입력 장치 선택:"
msgstr "마이크 입력 장치 선택:"

msgid "시스템 기본 마이크"
msgstr "시스템 기본 마이크"

msgid "💬 텍스트 대화"
msgstr "💬 텍스트 대화"

msgid "설정"
msgstr "설정"

msgid "종료"
msgstr "종료"

msgid "실행을 취소했습니다."
msgstr "실행을 취소했습니다."

msgid "코드 실행 시간이 너무 길어 중단했습니다."
msgstr "코드 실행 시간이 너무 길어 중단했습니다."

msgid "위험한 파이썬 작업 감지: {matched}"
msgstr "위험한 파이썬 작업 감지: {matched}"

msgid "언어 변경"
msgstr "언어 변경"

msgid "언어 설정이 저장됐어요. 재시작 후 적용됩니다."
msgstr "언어 설정이 저장됐어요. 재시작 후 적용됩니다."

msgid "로그 파일 폴더 열기"
msgstr "로그 파일 폴더 열기"
```

### `en/LC_MESSAGES/ari.po`

```po
# Ari Voice Assistant — English
msgid ""
msgstr ""
"Content-Type: text/plain; charset=UTF-8\n"
"Language: en\n"

msgid "아리 설정"
msgstr "Ari Settings"

msgid "마이크 입력 장치 선택:"
msgstr "Select Microphone Input:"

msgid "시스템 기본 마이크"
msgstr "System Default Microphone"

msgid "💬 텍스트 대화"
msgstr "💬 Text Chat"

msgid "설정"
msgstr "Settings"

msgid "종료"
msgstr "Exit"

msgid "실행을 취소했습니다."
msgstr "Execution cancelled."

msgid "코드 실행 시간이 너무 길어 중단했습니다."
msgstr "Code execution timed out and was stopped."

msgid "위험한 파이썬 작업 감지: {matched}"
msgstr "Dangerous Python operation detected: {matched}"

msgid "언어 변경"
msgstr "Language Changed"

msgid "언어 설정이 저장됐어요. 재시작 후 적용됩니다."
msgstr "Language setting saved. Please restart to apply."

msgid "로그 파일 폴더 열기"
msgstr "Open Log Folder"
```

### `ja/LC_MESSAGES/ari.po`

```po
# Ari Voice Assistant — 日本語
msgid ""
msgstr ""
"Content-Type: text/plain; charset=UTF-8\n"
"Language: ja\n"

msgid "아리 설정"
msgstr "Ariの設定"

msgid "마이크 입력 장치 선택:"
msgstr "マイク入力デバイスの選択:"

msgid "시스템 기본 마이크"
msgstr "システム既定のマイク"

msgid "💬 텍스트 대화"
msgstr "💬 テキストチャット"

msgid "설정"
msgstr "設定"

msgid "종료"
msgstr "終了"

msgid "실행을 취소했습니다."
msgstr "実行をキャンセルしました。"

msgid "코드 실행 시간이 너무 길어 중단했습니다."
msgstr "コードの実行時間が長すぎたため、停止しました。"

msgid "위험한 파이썬 작업 감지: {matched}"
msgstr "危険なPython操作を検出しました: {matched}"

msgid "언어 변경"
msgstr "言語変更"

msgid "언어 설정이 저장됐어요. 재시작 후 적용됩니다."
msgstr "言語設定を保存しました。再起動後に適用されます。"

msgid "로그 파일 폴더 열기"
msgstr "ログフォルダを開く"
```

---

## 11. 설정 연동

### `settings_schema.py`

```python
"language": "ko",   # "ko" | "en" | "ja"
```

### 설정 UI 언어 선택 + 로그 폴더 버튼

```python
# settings_dialog.py — _() 는 메서드 내부에서 호출
def _init_general_tab(self):
    lang_combo = QComboBox()
    lang_combo.addItem("한국어", "ko")
    lang_combo.addItem("English", "en")
    lang_combo.addItem("日本語", "ja")
    idx = lang_combo.findData(ConfigManager.get("language", "ko"))
    lang_combo.setCurrentIndex(idx if idx >= 0 else 0)

    def on_lang_changed(idx):
        lang = lang_combo.itemData(idx)
        ConfigManager.set_value("language", lang)
        QMessageBox.information(
            self,
            _("언어 변경"),
            _("언어 설정이 저장됐어요. 재시작 후 적용됩니다.")
        )
    lang_combo.currentIndexChanged.connect(on_lang_changed)

    def _open_log_folder():
        from core.resource_manager import ResourceManager
        import os
        os.startfile(ResourceManager.get_writable_path("logs"))

    log_btn = QPushButton(_("로그 파일 폴더 열기"))
    log_btn.clicked.connect(_open_log_folder)
```

---

## 12. 스크립트

### `scripts/extract_strings.py`

```python
"""_() 문자열 자동 추출 → .pot 생성. 실행: python scripts/extract_strings.py"""
import subprocess, os

BASE = os.path.dirname(os.path.dirname(__file__))
OUTPUT = os.path.join(BASE, "i18n", "locales", "ari.pot")
SOURCES = ["ui", "agent", "core", "commands", "memory", "services", "i18n"]

src_files = []
for d in SOURCES:
    for root, _, files in os.walk(os.path.join(BASE, d)):
        for f in files:
            if f.endswith(".py"):
                src_files.append(os.path.join(root, f))

subprocess.run([
    "xgettext", "--language=Python",
    "--keyword=_", "--keyword=ngettext:1,2",
    "--output=" + OUTPUT, "--from-code=UTF-8",
    "--package-name=Ari",
] + src_files, check=True)
print(f"Extracted: {OUTPUT}")
print("Next: add translations to each .po file, then run compile_po.py")
```

### `scripts/compile_po.py`

```python
"""po → mo 컴파일. 실행: python scripts/compile_po.py
필요: pip install Babel  또는  gettext 설치 후 msgfmt 사용"""
import subprocess, os

LOCALES = os.path.join(os.path.dirname(os.path.dirname(__file__)), "i18n", "locales")
for lang in os.listdir(LOCALES):
    po = os.path.join(LOCALES, lang, "LC_MESSAGES", "ari.po")
    mo = po.replace(".po", ".mo")
    if os.path.exists(po):
        subprocess.run(["msgfmt", "-o", mo, po], check=True)
        print(f"Compiled: {lang} -> {mo}")
```

**배포 시 주의:** `.mo` 파일을 레포에 미리 포함시켜 배포 환경에서 `msgfmt` 설치 불필요하게 하는 것을 권장.

---

## 13. 구현 순서

```
# Phase 0 — 기반 구조
1.  i18n/translator.py
2.  i18n/__init__.py
3.  i18n/locales/ko/LC_MESSAGES/ari.po
4.  i18n/locales/en/LC_MESSAGES/ari.po
5.  i18n/locales/ja/LC_MESSAGES/ari.po
6.  scripts/extract_strings.py
7.  scripts/compile_po.py + .mo 생성
8.  settings_schema.py — "language": "ko" 추가
9.  Main.py — i18n_init() 모든 import 전 최상단에 추가

# Phase 1 — 프롬프트 / LLM 언어 분기 (UI 전에 먼저)
10. agent/llm_provider.py — _TOOL_INSTRUCTION → _get_tool_instruction() 함수화
    + _build_system() 언어 주입
11. core/rp_generator.py — build_system_prompt() 감정 태그 언어 분기
12. agent/agent_planner.py — _get_decompose_prompt() + 한/영 2벌 프롬프트
    (_FIX_PROMPT, _VERIFY_PROMPT, _REFLECT_PROMPT 등 나머지도 동일 패턴)

# Phase 2 — LLM 결과물 필드명 변경 (한 번에 처리)
13. agent/safety_checker.py — summary_kr → summary 필드명 변경
14. agent/goal_predictor.py — warning_kr → warning 변경
15. agent/regression_guard.py — alert_message _() 적용
16. agent/autonomous_executor.py, confirmation_manager.py,
    skill_optimizer.py 등 — summary_kr 참조 전부 summary로 변경
17. validate_repo.py + 전체 테스트 실행 (누락 확인)

# Phase 3 — UI
18. ui/settings_dialog.py — _() 적용 + 언어 콤보박스 + 로그 폴더 버튼
19. ui/settings_llm_page.py — _() 적용
20. ui/settings_tts_page.py — _() 적용
21. ui/settings_plugin_page.py — _() 적용
22. ui/tray_icon.py — _() 적용
23. ui/text_interface.py — _() 적용

# Phase 4 — TTS 발화 / 나머지
24. agent/autonomous_executor.py — _() 적용
25. agent/agent_orchestrator.py — _() 적용
26. core/VoiceCommand.py — _() 적용
27. commands/ai_command.py — _() 적용
28. agent/weekly_report.py, proactive_scheduler.py 등 — _() 적용
29. tts/ 초기화 — 언어별 기본 음성 전환
30. core/plugin_loader.py — PluginContext.translate 주입
31. scripts/compile_po.py 재실행 (신규 문자열 반영)
```

---

## 14. Claude Code 검증 체크리스트

```
# Phase 0 기반 구조
[ ] i18n_init()이 Main.py에서 모든 import 전 최상단에 위치
[ ] _("아리 설정") → "Ari Settings" (en) / "Ariの設定" (ja) / "아리 설정" (ko)
[ ] _("주의: {msg}", msg="오류") 변수 보간 동작
[ ] ngettext 단수/복수 동작
[ ] .mo 없을 때 NullTranslations 폴백 — 앱 크래시 없음
[ ] settings_schema에 "language": "ko" 포함

# Phase 1 프롬프트
[ ] _get_tool_instruction() — 언어별 다른 지시문 반환
[ ] _build_system() — 언어별 base_prompt + lang_instruction 포함
[ ] rp_generator — 감정 태그 언어별 분기 (en: joy/sad/..., ja: 喜び/悲しみ/...)
[ ] _get_decompose_prompt("en") → 영어 플래너 프롬프트
[ ] _get_decompose_prompt("ja") → 영어 프롬프트 반환 (일본어 응답은 lang_instruction으로 유도)

# Phase 2 필드명 변경
[ ] summary_kr → summary 전체 변경, AttributeError 없음
[ ] warning_kr → warning 전체 변경, AttributeError 없음
[ ] validate_repo.py 통과
[ ] 전체 테스트 통과

# Phase 3 UI
[ ] 설정 창 제목 언어별 정상 표시
[ ] 트레이 메뉴 언어별 정상 표시
[ ] 언어 콤보박스 변경 → 재시작 안내 메시지
[ ] 로그 폴더 열기 버튼 동작

# Phase 4 TTS / 발화
[ ] en 모드에서 TTS 발화 영어로 출력
[ ] ja 모드에서 TTS 발화 일본어로 출력
[ ] LLM 응답이 설정 언어로 나옴 (en/ja 각각)
[ ] Edge TTS 음성 — en: en-US-JennyNeural, ja: ja-JP-NanamiNeural
[ ] 사용자 지정 음성 있으면 기본값 무시
[ ] PluginContext.translate() 동작

# 스크립트
[ ] extract_strings.py → .pot 생성
[ ] compile_po.py → 3개 언어 .mo 생성
[ ] .mo 파일 레포에 포함 확인

# 기존 테스트
[ ] tests/ 전부 통과
```

---

## 15. 주의사항

**`_()` 모듈 레벨 사용 금지:**
`i18n_init()` 이전에 평가되는 모든 코드(모듈 레벨 상수, 클래스 변수)에
`_()` 사용 금지. 반드시 함수/메서드 내부에서만 호출.
`_TOOL_INSTRUCTION` 같은 기존 상수는 전부 함수로 변환 필요.

**`summary_kr` 필드 변경 80건:**
누락 시 `AttributeError`로 앱 중단. Phase 2를 별도로 분리해 한 번에 처리하고
바로 `validate_repo.py` 실행해서 확인.

**플래너 프롬프트 일본어:**
일본어는 영어 프롬프트 + `lang_instruction`("常に日本語で応答")으로 처리.
대부분의 LLM이 이 방식으로 일본어 응답을 충분히 잘 생성함.

**로그 영어 고정:**
버그 리포트 시 언어 설정과 무관하게 개발자가 읽을 수 있도록 영어 고정.
사용자는 설정 UI의 "로그 파일 폴더 열기" 버튼으로 접근.

**웨이크워드:**
기본값이 "아리야"로 한국어 고정이지만, 설정에서 변경 가능.
영어/일본어 사용자를 위해 설정 UI에 안내 문구 추가 권장.
예: "영어 사용 시 'Hey Ari' 등으로 변경하세요."

**일본어 번역 품질:**
`.po` 파일 일본어 번역은 초안 수준. 실제 배포 전 원어민 검수 권장.

**배포 시 `.mo` 포함:**
`.mo` 컴파일에 `msgfmt` 필요. 배포 환경에서 설치 부담 없애려면
`.mo` 파일을 미리 컴파일해서 레포에 포함.
