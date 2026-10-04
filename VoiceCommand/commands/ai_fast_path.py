"""AICommand의 빠른 로컬 처리: 판단 엔진 결과를 기존 도구 처리기로 한 번 실행한다."""
import json
import logging
from typing import TYPE_CHECKING, Callable, Optional

from i18n.translator import _

if TYPE_CHECKING:
    from agent.decision.engine import FastPathResult


class FastPathMixin:
    """`_execute_tool_calls`와 `_emit_user_message`를 가진 명령 클래스에 섞어 쓴다."""

    _INSTANT_ACK_RESPONSE_POOL = {
        "good": ("확인하겠습니다.", "바로 살펴보겠습니다."),
        "calm": ("잠시만요.", "곧 확인하겠습니다."),
        "down": ("조금만 기다려 주세요.", "바로 살펴보겠습니다."),
    }
    _FAST_PATH_RESPONSE_POOLS = {
        "get_running_apps": {
            "good": ("실행 중인 앱 목록을 확인했습니다.",),
            "calm": ("실행 중인 앱 목록을 확인했습니다.",),
            "down": ("실행 중인 앱 목록을 확인했습니다.",),
        },
        "take_screenshot": {
            "good": ("스크린샷을 저장했습니다.",),
            "calm": ("스크린샷을 저장했습니다.",),
            "down": ("스크린샷을 저장했습니다.",),
        },
        "adjust_volume": {
            "good": ("볼륨을 조절했습니다.",),
            "calm": ("볼륨을 조절했습니다.",),
            "down": ("볼륨을 조절했습니다.",),
        },
    }
    _FAST_PATH_MESSAGES = {
        name: phrases["calm"][0]
        for name, phrases in _FAST_PATH_RESPONSE_POOLS.items()
    }
    _RUNNING_APPS_SHOWN = 10

    def decision_engine(self):
        """실행 중인 로컬 판단 엔진을 반환하거나 처음 생성한다."""
        if not hasattr(self, "_decision_engine"):
            from agent.decision.engine import LocalDecisionEngine
            from core.resource_manager import ResourceManager

            self._decision_engine = LocalDecisionEngine(
                ResourceManager.get_bundle_path("resources/decision")
            )
        return self._decision_engine

    def try_fast_path(self, text: str) -> Optional["FastPathResult"]:
        """선택적 로컬 분류 실패는 기존 대화 경로에 영향을 주지 않는다."""
        try:
            from core.config_manager import ConfigManager

            mode = ConfigManager.get("local_decision_mode", "fast")
            if not isinstance(mode, str) or mode not in {"shadow", "fast", "adaptive"}:
                return None
            if ConfigManager.get("local_decision_engine_enabled", True) is not True:
                return None
            return self.decision_engine().try_fast_path(text)
        except Exception:
            return None

    @staticmethod
    def _fast_handler_failed(result) -> bool:
        if isinstance(result, bool):
            return not result
        if isinstance(result, dict) and result.get("success") is False:
            return True
        if isinstance(result, str):
            normalized = result.strip().casefold()
            return normalized.startswith(
                (
                    "오류:",
                    "error:",
                    "failed:",
                    "failed to adjust volume",
                    "볼륨 조절 실패",
                    "실행 앱 목록 조회 실패",
                    "スクリーンショットの保存に失敗",
                    # 현재 언어로 번역된 실패 문구도 실패로 본다.
                    _("볼륨 조절 실패").casefold(),
                    _("실행 앱 목록 조회 실패: {error}").split("{", 1)[0].strip().casefold(),
                )
            )
        return result is None

    @classmethod
    def _running_apps_summary(cls, handler_result) -> Optional[str]:
        """음성 응답이 앱 이름 수백 개를 읽지 않도록 처리기의 JSON 목록을 줄인다."""
        try:
            payload = json.loads(handler_result)
        except (TypeError, ValueError):
            return None
        apps = payload.get("apps") if isinstance(payload, dict) else None
        if not isinstance(apps, list) or not apps:
            return None
        count = payload.get("count")
        count = count if isinstance(count, int) else len(apps)
        shown = ", ".join(str(app) for app in apps[:cls._RUNNING_APPS_SHOWN])
        if count > cls._RUNNING_APPS_SHOWN:
            shown += " …"
        phrases = {
            bucket: ("실행 중인 앱이 {count}개 있어요: {apps}",)
            for bucket in ("good", "calm", "down")
        }
        return cls._fixed_response(
            "get_running_apps",
            phrases,
            values={"count": count, "apps": shown},
        )

    def _fast_response(self, name: str, handler_result: Optional[str]) -> Optional[str]:
        if name == "get_current_time" and handler_result:
            return str(handler_result)

        phrases = self._FAST_PATH_RESPONSE_POOLS.get(name)
        if not phrases:
            return None
        if name == "take_screenshot" and handler_result:
            path_phrases = {
                bucket: ("스크린샷을 저장했습니다: {path}",)
                for bucket in ("good", "calm", "down")
            }
            return self._fixed_response(
                name,
                path_phrases,
                values={"path": handler_result},
            )
        if name == "get_running_apps" and handler_result:
            summary = self._running_apps_summary(handler_result)
            if summary:
                return summary
            list_phrases = {
                bucket: ("실행 중인 앱 목록입니다.\n{apps}",)
                for bucket in ("good", "calm", "down")
            }
            return self._fixed_response(
                name,
                list_phrases,
                values={"apps": handler_result},
            )
        return self._fixed_response(name, phrases)

    @staticmethod
    def _fixed_response(
        name: str,
        phrases: dict[str, tuple[str, ...]],
        values: dict | None = None,
        avoid_phrase: str = "",
    ) -> str:
        from agent.speech_scheduler import choose_phrase
        from core.config_manager import ConfigManager
        from core.mood_state import get_mood_state

        try:
            overrides = ConfigManager.get("fixed_responses", {})
        except (OSError, RuntimeError, TypeError, ValueError):
            overrides = {}
        override = overrides.get(name) if isinstance(overrides, dict) else None
        if isinstance(override, dict):
            merged = dict(phrases)
            for bucket in ("good", "calm", "down"):
                value = override.get(bucket)
                if isinstance(value, str) and value.strip():
                    merged[bucket] = (value.strip(),)
                elif isinstance(value, (list, tuple)):
                    options = tuple(
                        item.strip()
                        for item in value
                        if isinstance(item, str) and item.strip()
                    )
                    if options:
                        merged[bucket] = options
            phrases = merged
        try:
            mood_state = get_mood_state()
        except (ImportError, OSError, RuntimeError, TypeError, ValueError):
            mood_state = None
        return choose_phrase(
            phrases,
            mood_state,
            translator=_,
            values=values,
            avoid_phrase=avoid_phrase,
        )

    def get_instant_ack_phrase(self) -> str:
        """직전 문구를 피해서 즉시 반응 문구를 고른다."""
        previous = getattr(self, "_last_instant_ack_phrase", "")
        phrase = self._fixed_response(
            "instant_ack",
            self._INSTANT_ACK_RESPONSE_POOL,
            avoid_phrase=previous,
        )
        if phrase:
            self._last_instant_ack_phrase = phrase
        return phrase

    def _decision_engine_call(self, method: str, *args) -> None:
        engine = getattr(self, "_decision_engine", None)
        if engine is None:
            return
        try:
            getattr(engine, method)(*args)
        except Exception:
            # 지표 기록 실패가 명령 처리를 막으면 안 된다.
            logging.debug("[AICommand] 판단 엔진 지표 기록 실패: %s", method, exc_info=True)

    def _execute_fast_path_result(
        self,
        result,
        *,
        tool_result_callback: Optional[Callable[[str, Optional[str]], None]] = None,
    ) -> bool:
        """아무것도 실행되지 않았을 때만 False를 반환해 호출자가 대화 경로를 유지하게 한다."""
        name = str(getattr(result, "tool_name", "") or "")
        arguments = getattr(result, "arguments", {})
        allowed = False
        if name and isinstance(arguments, dict):
            try:
                from agent.decision.candidates import is_direct_allowed

                allowed = is_direct_allowed(name, "fast")
            except Exception:
                allowed = False
        if not allowed:
            self._decision_engine_call("record", "llm_fallback")
            return False

        results = self._execute_tool_calls(
            [{"id": "fast_path_1", "name": name, "arguments": arguments}],
            tool_result_callback=tool_result_callback,
        )
        handler_result = results[0] if results else None
        # 처리기가 이미 부작용을 냈을 수 있으므로 실패는 한 번만 안내하고
        # 대화 경로로 다시 시도하지 않는다.
        if self._fast_handler_failed(handler_result):
            self._decision_engine_call("record", "execution_failed")
            self._emit_user_message(
                str(handler_result) if handler_result else _("요청한 작업을 완료하지 못했어요.")
            )
            return True
        self._decision_engine_call("note_executed", result)
        response = self._fast_response(name, handler_result)
        if response:
            self._emit_user_message(response)
        return True
