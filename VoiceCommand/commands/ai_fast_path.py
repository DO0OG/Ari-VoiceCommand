"""AICommand의 빠른 로컬 처리: 판단 엔진 결과를 기존 도구 처리기로 한 번 실행한다."""
from typing import TYPE_CHECKING, Callable, Optional

from i18n.translator import _

if TYPE_CHECKING:
    from agent.decision.engine import FastPathResult


class FastPathMixin:
    """`_execute_tool_calls`와 `_emit_user_message`를 가진 명령 클래스에 섞어 쓴다."""

    _FAST_PATH_MESSAGES = {
        "get_running_apps": "실행 중인 앱 목록을 확인했습니다.",
        "take_screenshot": "스크린샷을 저장했습니다.",
        "adjust_volume": "볼륨을 조절했습니다.",
    }

    def try_fast_path(self, text: str) -> Optional["FastPathResult"]:
        """선택적 로컬 분류 실패는 기존 대화 경로에 영향을 주지 않는다."""
        try:
            from core.config_manager import ConfigManager

            mode = ConfigManager.get("local_decision_mode", "off")
            if not isinstance(mode, str) or mode not in {"shadow", "fast", "adaptive"}:
                return None
            if ConfigManager.get("local_decision_engine_enabled", True) is not True:
                return None
            from agent.decision.engine import LocalDecisionEngine
            from core.resource_manager import ResourceManager

            if not hasattr(self, "_decision_engine"):
                self._decision_engine = LocalDecisionEngine(
                    ResourceManager.get_bundle_path("resources/decision")
                )
            return self._decision_engine.try_fast_path(text)
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

    def _fast_response(self, name: str, handler_result: Optional[str]) -> Optional[str]:
        if name == "get_current_time" and handler_result:
            return str(handler_result)

        message = self._FAST_PATH_MESSAGES.get(name)
        if not message:
            return None
        if name == "take_screenshot" and handler_result:
            return _("스크린샷을 저장했습니다: {path}").format(path=handler_result)
        if name == "get_running_apps" and handler_result:
            return _("실행 중인 앱 목록입니다.\n{apps}").format(apps=handler_result)
        return _(message)

    def _decision_engine_call(self, method: str, *args) -> None:
        engine = getattr(self, "_decision_engine", None)
        if engine is None:
            return
        try:
            getattr(engine, method)(*args)
        except Exception:
            pass

    def _execute_fast_path_result(
        self,
        result,
        *,
        tool_result_callback: Optional[Callable[[str, Optional[str]], None]] = None,
    ) -> bool:
        """Return False only when nothing ran, so the caller keeps the conversation path."""
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
        # The handler may already have had side effects, so a failure is reported
        # once and never retried through the conversation path.
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
