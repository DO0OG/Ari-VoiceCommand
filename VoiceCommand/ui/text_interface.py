"""
텍스트 채팅 인터페이스 (Text Interface)

v2.1 — theme.py / common.py 기반 리팩토링:
  - 중복 색상·폰트 상수 제거, ui.theme 임포트로 통합
  - TitleBar가 common.PanelTitleBar 사용
  - runtime import → 모듈 상단 지연 임포트로 이동
  - 창 숨겨질 때 제안 타이머 정지 (showEvent/hideEvent)

v2.0 — 실행 대시보드(ExecutionDashboardPanel), 선제적 제안 바(ProactiveSuggestionBar),
        메모리 패널 버튼(🧠), 스케줄러 패널 버튼(📅) 추가.
"""
import logging
from datetime import datetime
from typing import Optional

from PySide6.QtCore import Qt, QThread, Signal, QTimer, QPropertyAnimation, QEasingCurve, QRect
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QApplication, QFrame, QHBoxLayout, QLabel, QLineEdit,
    QMainWindow, QPushButton, QScrollArea, QVBoxLayout, QWidget,
)

# ── 조건부 임포트 (런타임에 없을 수 있는 모듈) ────────────────────────────────
try:
    from VoiceCommand import parse_emotion_text, EMOTION_EMOJI
except Exception as _e:
    logging.debug(f"VoiceCommand 임포트 건너뜀: {_e}")
    parse_emotion_text = None
    EMOTION_EMOJI = {}

try:
    from memory.user_context import get_context_manager
except Exception as _e:
    logging.debug(f"memory.user_context 임포트 건너뜀: {_e}")
    get_context_manager = None

# UI 공용 모듈
from ui.common import (
    apply_shadow, clear_layout,
    PanelTitleBar,
)
from ui.theme import (
    FONT_KO, FONT_SIZE_LARGE, FONT_SIZE_SMALL,
    COLOR_PRIMARY, COLOR_PRIMARY_DARK, COLOR_ACCENT, COLOR_MUTED, COLOR_MUTED_LIGHT,
    COLOR_SUCCESS, COLOR_WARNING, COLOR_DANGER,
    COLOR_TEXT_PRIMARY,
    COLOR_BG_MAIN, COLOR_BG_WHITE, COLOR_BG_INPUT, COLOR_BG_CHAT_USER, COLOR_BG_CHAT_AARI,
    COLOR_BG_STATUS, COLOR_BG_DASHBOARD, COLOR_BG_SUGGESTION,
    COLOR_BG_CHIP_PRIMARY, COLOR_TITLEBAR, COLOR_BORDER_LIGHT,
    SHADOW_BLUR, SHADOW_OFFSET,
    MARGIN_PANEL, SPACING_LG,
    ANIM_FAST, ANIM_NORMAL,
    SUGGESTION_REFRESH, STATUS_REFRESH, DASHBOARD_AUTO_HIDE,
    WINDOW_W_CHAT, WINDOW_H_CHAT,
    SCROLLBAR_STYLE, CHAT_INPUT_STYLE,
    close_btn_style,
)
from ui import theme as theme_module

logger = logging.getLogger(__name__)

# 단계 상태별 아이콘
_STEP_ICON = {
    "pending": "⏳", "running": "⚙️",
    "done": "✅", "failed": "❌", "fixed": "🔧",
}


# ── 채팅 위젯 ────────────────────────────────────────────────────────────────

class ChatWidget(QFrame):
    """채팅 메시지를 표시하는 위젯. 최대 MAX_MESSAGES개 메시지 유지."""

    MAX_MESSAGES = 50

    def __init__(self):
        super().__init__()
        self.history = []
        self.setFrameStyle(QFrame.StyledPanel)
        self.setStyleSheet("QFrame { background-color: transparent; border: none; }")
        lay = QVBoxLayout(self)
        lay.setAlignment(Qt.AlignTop)
        lay.setSpacing(SPACING_LG)

    def render_history(self) -> None:
        clear_layout(self.layout())
        for item in self.history[-self.MAX_MESSAGES:]:
            self._add_message_widget(item["message"], bool(item["is_user"]))

    def add_message(self, message: str, is_user: bool = True) -> None:
        self.history.append({"message": message, "is_user": is_user})
        if len(self.history) > self.MAX_MESSAGES:
            self.history = self.history[-self.MAX_MESSAGES:]
        self.render_history()

    def _add_message_widget(self, message: str, is_user: bool) -> None:
        timestamp = datetime.now().strftime("%H:%M:%S")
        display_message = message
        if not is_user and parse_emotion_text:
            emotion, pure_text = parse_emotion_text(message)
            emoji = EMOTION_EMOJI.get(emotion, "")
            if pure_text:
                display_message = f"{emoji} {pure_text}".strip() if emoji else pure_text

        sender_name  = "나" if is_user else "아리"
        sender_color = COLOR_PRIMARY if is_user else COLOR_ACCENT
        bg_color     = COLOR_BG_CHAT_USER if is_user else COLOR_BG_CHAT_AARI
        corner_style = "border-top-right-radius: 0px; margin-left: 40px;" if is_user \
                       else "border-top-left-radius: 0px; margin-right: 40px;"

        msg_frame = QFrame()
        msg_lay = QVBoxLayout(msg_frame)
        msg_lay.setContentsMargins(15, 10, 15, 10)

        sender_lbl = QLabel(sender_name)
        sender_lbl.setFont(QFont(FONT_KO, FONT_SIZE_SMALL + 1, QFont.Bold))
        sender_lbl.setStyleSheet(f"color: {sender_color};")

        msg_lbl = QLabel(display_message)
        msg_lbl.setWordWrap(True)
        msg_lbl.setFont(QFont(FONT_KO, FONT_SIZE_LARGE))
        msg_lbl.setStyleSheet(f"color: {COLOR_TEXT_PRIMARY}; margin: 2px 0px;")

        time_lbl = QLabel(timestamp)
        time_lbl.setFont(QFont(FONT_KO, FONT_SIZE_SMALL))
        time_lbl.setStyleSheet(f"color: {COLOR_MUTED_LIGHT};")
        time_lbl.setAlignment(Qt.AlignRight)

        msg_lay.addWidget(sender_lbl)
        msg_lay.addWidget(msg_lbl)
        msg_lay.addWidget(time_lbl)
        msg_frame.setStyleSheet(
            f"QFrame {{ background-color: {bg_color}; border-radius: 12px; {corner_style} }}"
        )
        self.layout().addWidget(msg_frame)

    def refresh_theme(self) -> None:
        self.layout().setSpacing(theme_module.SPACING_LG)
        self.render_history()


# ── 실행 대시보드 패널 ───────────────────────────────────────────────────────

class ExecutionDashboardPanel(QFrame):
    """에이전트 실행 중 step-by-step 진행 상황을 표시하는 접이식 패널."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._steps: dict = {}
        self._build_ui()
        self.hide()

    def _build_ui(self) -> None:
        self.setStyleSheet(f"""
            QFrame {{ background: {COLOR_BG_DASHBOARD};
                      border-bottom: 1px solid rgba(74,144,226,60); }}
        """)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(14, 8, 14, 8)
        outer.setSpacing(4)

        header = QHBoxLayout()
        self._title_lbl = QLabel("🤖 실행 중...")
        self._title_lbl.setFont(QFont(FONT_KO, FONT_SIZE_SMALL + 1, QFont.Bold))
        self._title_lbl.setStyleSheet(f"color: {COLOR_PRIMARY};")
        header.addWidget(self._title_lbl)
        header.addStretch()

        self._iter_lbl = QLabel("")
        self._iter_lbl.setFont(QFont(FONT_KO, FONT_SIZE_SMALL))
        self._iter_lbl.setStyleSheet(f"color: {COLOR_MUTED};")
        header.addWidget(self._iter_lbl)
        outer.addLayout(header)

        self._steps_widget = QWidget()
        self._steps_lay = QVBoxLayout(self._steps_widget)
        self._steps_lay.setContentsMargins(0, 2, 0, 0)
        self._steps_lay.setSpacing(2)
        outer.addWidget(self._steps_widget)

        self._summary_lbl = QLabel("")
        self._summary_lbl.setFont(QFont(FONT_KO, FONT_SIZE_SMALL))
        self._summary_lbl.setWordWrap(True)
        self._summary_lbl.setStyleSheet("color: #555;")
        outer.addWidget(self._summary_lbl)

    # ── Progress 이벤트 처리 ──────────────────────────────────────────────────

    def on_progress(self, event_type: str, **kwargs) -> None:
        """오케스트레이터 progress 이벤트 처리 (메인 스레드에서 호출)."""
        if event_type == "plan_ready":
            self._steps.clear()
            steps     = kwargs.get("steps", [])
            iteration = kwargs.get("iteration", 0)
            self._title_lbl.setText(f"🤖 계획 {len(steps)}단계")
            self._iter_lbl.setText(f"시도 {iteration + 1}회")
            for s in steps:
                self._steps[s["id"]] = {"desc": s["desc"], "type": s["type"], "status": "pending"}
            self._rebuild_steps()
            self._summary_lbl.setText("")
            self.show()

        elif event_type == "step_start":
            sid = kwargs.get("step_id")
            if sid in self._steps:
                self._steps[sid]["status"] = "running"
                self._rebuild_steps()

        elif event_type == "step_done":
            sid       = kwargs.get("step_id")
            success   = kwargs.get("success", True)
            was_fixed = kwargs.get("was_fixed", False)
            if sid in self._steps:
                self._steps[sid]["status"] = ("fixed" if was_fixed
                                              else ("done" if success else "failed"))
                self._rebuild_steps()

        elif event_type == "verify_start":
            self._title_lbl.setText("🔍 검증 중...")

        elif event_type in ("achieved", "failed", "not_achieved"):
            summary = kwargs.get("summary", "")
            icon    = "✅" if event_type == "achieved" else "⚠️"
            label   = "완료" if event_type == "achieved" else "미완료"
            self._title_lbl.setText(f"{icon} {label}")
            self._summary_lbl.setText(summary[:120])
            if event_type == "achieved":
                QTimer.singleShot(DASHBOARD_AUTO_HIDE, self.hide)

        elif event_type == "replan":
            iteration = kwargs.get("iteration", 0)
            reason    = kwargs.get("reason", "")
            self._iter_lbl.setText(f"재계획 (시도 {iteration + 2}회)")
            self._summary_lbl.setText(f"♻️ {reason[:80]}")
            self._steps.clear()
            self._rebuild_steps()

    def _rebuild_steps(self) -> None:
        clear_layout(self._steps_lay)
        _step_color = {
            "running": COLOR_PRIMARY, "done": COLOR_SUCCESS,
            "failed": COLOR_DANGER,   "fixed": COLOR_WARNING,
        }
        for sid in sorted(self._steps):
            info   = self._steps[sid]
            status = info["status"]
            icon   = _STEP_ICON.get(status, "⏳")
            color  = _step_color.get(status, COLOR_MUTED)
            lbl = QLabel(f"{icon} {info['desc'][:60]}")
            lbl.setFont(QFont(FONT_KO, FONT_SIZE_SMALL))
            lbl.setStyleSheet(f"color: {color};")
            self._steps_lay.addWidget(lbl)

    def reset(self) -> None:
        self._steps.clear()
        self._rebuild_steps()
        self._title_lbl.setText("🤖 실행 중...")
        self._iter_lbl.setText("")
        self._summary_lbl.setText("")
        self.hide()

    def refresh_theme(self) -> None:
        self.setStyleSheet(f"""
            QFrame {{ background: {theme_module.COLOR_BG_DASHBOARD};
                      border-bottom: 1px solid rgba(74,144,226,60); }}
        """)
        self._title_lbl.setFont(QFont(theme_module.FONT_KO, theme_module.FONT_SIZE_SMALL + 1, QFont.Bold))
        self._title_lbl.setStyleSheet(f"color: {theme_module.COLOR_PRIMARY};")
        self._iter_lbl.setFont(QFont(theme_module.FONT_KO, theme_module.FONT_SIZE_SMALL))
        self._iter_lbl.setStyleSheet(f"color: {theme_module.COLOR_MUTED};")
        self._summary_lbl.setFont(QFont(theme_module.FONT_KO, theme_module.FONT_SIZE_SMALL))
        self._rebuild_steps()


# ── 선제적 제안 바 ────────────────────────────────────────────────────────────

class ProactiveSuggestionBar(QFrame):
    """시간 패턴·명령 빈도 기반 제안 칩을 표시하는 바."""

    suggestion_clicked = Signal(str)

    def __init__(self, ctx_manager=None, parent=None):
        super().__init__(parent)
        self._ctx = ctx_manager
        self._build_ui()
        self._refresh_timer = QTimer(self)
        self._refresh_timer.timeout.connect(self._refresh_suggestions)
        # 창이 표시될 때만 타이머 가동 (showEvent/hideEvent에서 제어)
        self._refresh_suggestions()

    def _build_ui(self) -> None:
        self.setStyleSheet(f"""
            QFrame {{ background: {COLOR_BG_SUGGESTION};
                      border-bottom: 1px solid rgba(74,144,226,40); }}
        """)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 6, 12, 6)
        lay.setSpacing(2)

        hint_lbl = QLabel("💡 자주 쓰는 명령")
        hint_lbl.setFont(QFont(FONT_KO, FONT_SIZE_SMALL))
        hint_lbl.setStyleSheet(f"color: {COLOR_MUTED};")
        lay.addWidget(hint_lbl)

        self._chips_row = QHBoxLayout()
        self._chips_row.setSpacing(6)
        self._chips_row.setAlignment(Qt.AlignLeft)
        lay.addLayout(self._chips_row)

    def _refresh_suggestions(self) -> None:
        # 기존 칩 제거
        while self._chips_row.count():
            item = self._chips_row.takeAt(0)
            if item and item.widget():
                item.widget().deleteLater()

        suggestions = self._build_suggestions()
        if not suggestions:
            self.hide()
            return

        for text, goal in suggestions[:4]:
            btn = QPushButton(text)
            btn.setFont(QFont(FONT_KO, FONT_SIZE_SMALL))
            btn.setCursor(Qt.PointingHandCursor)
            btn.setFixedHeight(26)
            btn.setStyleSheet(f"""
                QPushButton {{ background: {COLOR_BG_CHIP_PRIMARY}; color: {COLOR_PRIMARY};
                               border-radius: 13px; border: none; padding: 0 12px; }}
                QPushButton:hover {{ background: {COLOR_PRIMARY}; color: white; }}
            """)
            _goal = goal
            btn.clicked.connect(lambda checked=False, g=_goal: self.suggestion_clicked.emit(g))
            self._chips_row.addWidget(btn)

        self.show()

    def _build_suggestions(self) -> list:
        if not self._ctx:
            return []
        suggestions = []
        time_cmds = self._ctx.get_time_based_suggestions(limit=2)
        if time_cmds:
            for cmd in time_cmds:
                suggestions.append((f"⏰ {cmd}", cmd))
        for cmd in self._ctx.get_predicted_next_commands()[:2]:
            if not any(cmd == s[1] for s in suggestions):
                suggestions.append((f"→ {cmd}", cmd))
        return suggestions[:4]

    def update_context_manager(self, ctx_manager) -> None:
        self._ctx = ctx_manager
        self._refresh_suggestions()

    def start_timer(self) -> None:
        self._refresh_timer.start(SUGGESTION_REFRESH)

    def stop_timer(self) -> None:
        self._refresh_timer.stop()

    def refresh_theme(self) -> None:
        self.setStyleSheet(f"""
            QFrame {{ background: {theme_module.COLOR_BG_SUGGESTION};
                      border-bottom: 1px solid rgba(74,144,226,40); }}
        """)
        self._refresh_suggestions()


# ── AI 처리 스레드 ────────────────────────────────────────────────────────────

class TextInterfaceThread(QThread):
    """비동기 AI 응답 + 에이전트 실행 스레드."""

    response_ready = Signal(str)
    progress_event = Signal(str, dict)   # event_type, kwargs_dict

    def __init__(self, ai_assistant, query: str):
        super().__init__()
        self.ai_assistant = ai_assistant
        self.query = query

    def run(self) -> None:
        self._attach_progress_callback()
        try:
            response = self._execute_query()
            self.response_ready.emit(str(response))
        except Exception as e:
            logger.error(f"텍스트 처리 오류: {e}")
            self.response_ready.emit(f"오류가 발생했습니다: {e}")
        finally:
            self._detach_progress_callback()

    def _execute_query(self) -> str:
        # AICommand 경로 우선 시도 (tool calling, agent 포함)
        try:
            from VoiceCommand import _command_registry
            if _command_registry:
                from commands.ai_command import AICommand
                for command in _command_registry.commands:
                    if isinstance(command, AICommand):
                        result = command.run_interaction(self.query)
                        if result:
                            return result
        except Exception as e:
            logger.error(f"AICommand 경로 실행 실패: {e}")

        # 폴백: ai_assistant 직접 호출
        if hasattr(self.ai_assistant, "chat_with_tools"):
            response, _ = self.ai_assistant.chat_with_tools(self.query, include_context=True)
            return response
        if hasattr(self.ai_assistant, "process_query"):
            response, _, _ = self.ai_assistant.process_query(self.query)
            return response
        if hasattr(self.ai_assistant, "chat"):
            return self.ai_assistant.chat(self.query)
        return "죄송합니다. AI 응답 엔진을 초기화할 수 없습니다."

    def _attach_progress_callback(self) -> None:
        try:
            from agent.agent_orchestrator import get_orchestrator
            get_orchestrator().set_progress_callback(self._on_progress)
        except Exception as exc:
            logger.debug(f"오케스트레이터 progress 연결 생략: {exc}")

    def _detach_progress_callback(self) -> None:
        try:
            from agent.agent_orchestrator import get_orchestrator
            get_orchestrator().set_progress_callback(None)
        except Exception as exc:
            logger.debug(f"오케스트레이터 progress 해제 생략: {exc}")

    def _on_progress(self, event_type: str, **kwargs) -> None:
        self.progress_event.emit(event_type, kwargs)


# ── 커스텀 타이틀 바 ──────────────────────────────────────────────────────────

class TitleBar(PanelTitleBar):
    """채팅 창 타이틀 바. 공용 PanelTitleBar에 스케줄러/메모리 버튼 추가."""

    scheduler_btn_clicked = Signal()
    memory_btn_clicked    = Signal()

    def __init__(self, parent: QMainWindow):
        super().__init__("💬 아리와 대화하기", parent)
        # 닫기 버튼과 함께 타이틀 바에 포함될 아이콘 버튼
        self.add_button("📅", "예약 작업 관리",    self.scheduler_btn_clicked.emit)
        self.add_button("🧠", "아리의 기억 보기",  self.memory_btn_clicked.emit)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_pos = event.globalPos() - self._win.pos()

    def mouseMoveEvent(self, event):
        if event.buttons() == Qt.LeftButton and self._drag_pos is not None:
            self._win.move(event.globalPos() - self._drag_pos)

    def mouseReleaseEvent(self, event):
        self._drag_pos = None

    def refresh_theme(self) -> None:
        super().refresh_theme()


# ── 메인 텍스트 인터페이스 창 ────────────────────────────────────────────────

class TextInterface(QMainWindow):
    """말풍선 확장형 텍스트 인터페이스 메인 창."""

    def __init__(self, ai_assistant=None, tts_callback=None):
        super().__init__()
        self.ai_assistant    = ai_assistant
        self.tts_callback    = tts_callback
        self.processing_thread: Optional[TextInterfaceThread] = None
        self.context_manager = get_context_manager() if get_context_manager else None
        self._scheduler_panel = None
        self._memory_panel    = None

        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)

        self._init_ui()
        self._init_animations()

    # ── UI 구성 ───────────────────────────────────────────────────────────────

    def _init_ui(self) -> None:
        self.resize(WINDOW_W_CHAT, WINDOW_H_CHAT)
        central = QWidget()
        self.setCentralWidget(central)

        outer = QVBoxLayout(central)
        outer.setContentsMargins(MARGIN_PANEL, MARGIN_PANEL, MARGIN_PANEL, MARGIN_PANEL)

        self.bg_frame = QFrame()
        self.bg_frame.setObjectName("BgFrame")
        self.bg_frame.setStyleSheet(f"""
            #BgFrame {{ background-color: {COLOR_BG_MAIN};
                        border-radius: 15px;
                        border: 1px solid {COLOR_BORDER_LIGHT}; }}
        """)
        apply_shadow(self.bg_frame, SHADOW_BLUR, SHADOW_OFFSET)

        bg_lay = QVBoxLayout(self.bg_frame)
        bg_lay.setContentsMargins(0, 0, 0, 0)
        bg_lay.setSpacing(0)
        outer.addWidget(self.bg_frame)

        # 타이틀 바
        self.title_bar = TitleBar(self)
        self.title_bar.scheduler_btn_clicked.connect(self._open_scheduler_panel)
        self.title_bar.memory_btn_clicked.connect(self._open_memory_panel)
        bg_lay.addWidget(self.title_bar)

        # 기억 상태 패널
        status_frame = QFrame()
        status_frame.setStyleSheet(f"""
            QFrame {{ background: {COLOR_BG_STATUS};
                      border-bottom: 1px solid rgba(220,220,220,120); }}
        """)
        status_lay = QVBoxLayout(status_frame)
        status_lay.setContentsMargins(16, 8, 16, 8)
        status_lay.setSpacing(3)

        status_title = QLabel("기억 상태")
        status_title.setFont(QFont(FONT_KO, FONT_SIZE_SMALL + 1, QFont.Bold))
        status_title.setStyleSheet("color: #375a7f;")
        status_lay.addWidget(status_title)

        self.status_summary = QLabel("")
        self.status_summary.setWordWrap(True)
        self.status_summary.setFont(QFont(FONT_KO, FONT_SIZE_SMALL))
        self.status_summary.setStyleSheet("color: #4f5b66;")
        status_lay.addWidget(self.status_summary)
        bg_lay.addWidget(status_frame)

        # 실행 대시보드 (에이전트 실행 시 표시)
        self.dashboard = ExecutionDashboardPanel()
        bg_lay.addWidget(self.dashboard)

        # 채팅 영역
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setStyleSheet(SCROLLBAR_STYLE)
        self.chat_widget = ChatWidget()
        self.scroll_area.setWidget(self.chat_widget)
        bg_lay.addWidget(self.scroll_area)

        # 선제적 제안 바
        self.suggestion_bar = ProactiveSuggestionBar(self.context_manager)
        self.suggestion_bar.suggestion_clicked.connect(self._send_suggestion)
        bg_lay.addWidget(self.suggestion_bar)

        # 입력 영역
        input_frame = QFrame()
        input_frame.setFixedHeight(70)
        input_frame.setStyleSheet(f"""
            QFrame {{ background-color: {COLOR_BG_WHITE};
                      border-bottom-left-radius: 15px;
                      border-bottom-right-radius: 15px;
                      border-top: 1px solid #eeeeee; }}
        """)
        input_lay = QHBoxLayout(input_frame)
        input_lay.setContentsMargins(15, 10, 15, 15)
        input_lay.setSpacing(10)

        self.input_field = QLineEdit()
        self.input_field.setPlaceholderText("메시지 입력...")
        self.input_field.setFont(QFont(FONT_KO, FONT_SIZE_LARGE))
        self.input_field.setStyleSheet(CHAT_INPUT_STYLE)
        self.input_field.returnPressed.connect(self.send_message)
        input_lay.addWidget(self.input_field)

        self.send_btn = QPushButton("➤")
        self.send_btn.setFixedSize(36, 36)
        self.send_btn.setCursor(Qt.PointingHandCursor)
        self.send_btn.setStyleSheet(f"""
            QPushButton {{ background-color: {COLOR_PRIMARY}; color: white;
                           border-radius: 18px; font-weight: bold; font-size: 16px; }}
            QPushButton:hover {{ background-color: {COLOR_PRIMARY_DARK}; }}
            QPushButton:disabled {{ background-color: #cccccc; }}
        """)
        self.send_btn.clicked.connect(self.send_message)
        input_lay.addWidget(self.send_btn)
        bg_lay.addWidget(input_frame)

        # 초기 메시지 + 타이머
        self.chat_widget.add_message("안녕하세요! 무엇을 도와드릴까요?", is_user=False)
        self.refresh_status_panel()

        self._status_timer = QTimer(self)
        self._status_timer.timeout.connect(self.refresh_status_panel)
        self._status_timer.start(STATUS_REFRESH)

    def _init_animations(self) -> None:
        self.anim = QPropertyAnimation(self, b"geometry")
        self.anim.setDuration(ANIM_NORMAL)
        self.anim.setEasingCurve(QEasingCurve.OutBack)
        self.opacity_anim = QPropertyAnimation(self, b"windowOpacity")
        self.opacity_anim.setDuration(ANIM_FAST)

    # ── 창 표시/숨김 시 타이머 제어 ─────────────────────────────────────────

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.suggestion_bar.start_timer()

    def hideEvent(self, event) -> None:
        super().hideEvent(event)
        self.suggestion_bar.stop_timer()

    # ── 메시지 송수신 ─────────────────────────────────────────────────────────

    def send_message(self) -> None:
        query = self.input_field.text().strip()
        if not query or (self.processing_thread and self.processing_thread.isRunning()):
            return

        self.chat_widget.add_message(query, is_user=True)
        self.input_field.clear()
        self._set_ui_enabled(False)
        self.dashboard.reset()
        self.scroll_to_bottom()

        if self.ai_assistant:
            self.processing_thread = TextInterfaceThread(self.ai_assistant, query)
            self.processing_thread.response_ready.connect(self._handle_response)
            self.processing_thread.progress_event.connect(self._on_progress_event)
            self.processing_thread.finished.connect(lambda: self._set_ui_enabled(True))
            self.processing_thread.start()
        else:
            self._handle_response("AI 엔진이 연결되지 않았습니다.")
            self._set_ui_enabled(True)

    def _send_suggestion(self, goal: str) -> None:
        self.input_field.setText(goal)
        self.send_message()

    def _handle_response(self, response: str) -> None:
        self.chat_widget.add_message(response, is_user=False)
        self.scroll_to_bottom()
        self.refresh_status_panel()
        if self.tts_callback:
            self.tts_callback(response)

    def _on_progress_event(self, event_type: str, kwargs: dict) -> None:
        """워커 스레드 progress 이벤트 → 메인 스레드 대시보드 업데이트."""
        self.dashboard.on_progress(event_type, **kwargs)
        self.scroll_to_bottom()

    # ── UI 헬퍼 ───────────────────────────────────────────────────────────────

    def _set_ui_enabled(self, enabled: bool) -> None:
        self.input_field.setEnabled(enabled)
        self.send_btn.setEnabled(enabled)
        if enabled:
            self.input_field.setFocus()

    def scroll_to_bottom(self) -> None:
        QTimer.singleShot(50, lambda: self.scroll_area.verticalScrollBar().setValue(
            self.scroll_area.verticalScrollBar().maximum()
        ))

    def refresh_status_panel(self) -> None:
        if not self.context_manager:
            self.status_summary.setText("기억 시스템을 불러오지 못했습니다.")
            return
        try:
            predictions = self.context_manager.get_predicted_next_commands()
            topics = sorted(
                self.context_manager.context.get("conversation_topics", {}).items(),
                key=lambda x: x[1], reverse=True,
            )[:2]
            prefs = self.context_manager.get_top_preferences(limit=2)
            lines = []
            if topics:
                lines.append("주제 " + " · ".join(t for t, _ in topics))
            if predictions:
                lines.append("다음 추천 " + " → ".join(predictions))
            if prefs:
                lines.append("선호 " + " · ".join(prefs[:2]))
            if not lines:
                lines.append("대화를 이어가면 이곳에 요약이 표시됩니다.")
            self.status_summary.setText("\n".join(lines))
        except Exception as e:
            logger.debug(f"상태 패널 갱신 실패: {e}")

    # ── 사이드 패널 ───────────────────────────────────────────────────────────

    def _open_scheduler_panel(self) -> None:
        if self._scheduler_panel is None:
            try:
                from ui.scheduler_panel import SchedulerPanel
                from agent.scheduler import get_scheduler
                self._scheduler_panel = SchedulerPanel(scheduler=get_scheduler())
            except Exception as e:
                logger.error(f"스케줄러 패널 생성 실패: {e}")
                return
        geo = self.geometry()
        self._scheduler_panel.show_near(geo.right(), geo.top())

    def _open_memory_panel(self) -> None:
        if self._memory_panel is None:
            try:
                from ui.memory_panel import MemoryPanel
                self._memory_panel = MemoryPanel(ctx_manager=self.context_manager)
            except Exception as e:
                logger.error(f"메모리 패널 생성 실패: {e}")
                return
        geo = self.geometry()
        self._memory_panel.show_near(geo.right(), geo.top())

    # ── 애니메이션 & 위치 ────────────────────────────────────────────────────

    def show_near(self, target_x: int, target_y: int, target_width: int = 0, target_height: int = 0) -> None:
        screen = QApplication.primaryScreen().geometry()
        final_x = target_x + target_width + 10
        final_y = target_y + target_height // 2 - self.height() // 2
        if final_x + self.width() > screen.width():
            final_x = target_x - self.width() - 10
        final_y = max(20, min(final_y, screen.height() - self.height() - 40))

        start_rect = QRect(target_x + target_width // 2, target_y + target_height // 2, 1, 1)
        end_rect   = QRect(final_x, final_y, self.width(), self.height())

        try:
            self.opacity_anim.finished.disconnect(self.hide)
        except RuntimeError:
            pass

        self.setGeometry(start_rect)
        self.setWindowOpacity(0.0)
        self.show()

        self.anim.stop()
        self.anim.setEasingCurve(QEasingCurve.OutBack)
        self.anim.setStartValue(start_rect)
        self.anim.setEndValue(end_rect)
        self.anim.start()

        self.opacity_anim.stop()
        self.opacity_anim.setStartValue(0.0)
        self.opacity_anim.setEndValue(1.0)
        self.opacity_anim.start()

        self.activateWindow()
        self.input_field.setFocus()

    def close_with_animation(self) -> None:
        self.anim.stop()
        start_rect = self.geometry()
        end_rect   = QRect(start_rect.x(), start_rect.y() + 30, start_rect.width(), start_rect.height())

        self.anim.setEasingCurve(QEasingCurve.InBack)
        self.anim.setStartValue(start_rect)
        self.anim.setEndValue(end_rect)
        self.anim.start()

        try:
            self.opacity_anim.finished.disconnect(self.hide)
        except (RuntimeError, TypeError):
            pass

        self.opacity_anim.stop()
        self.opacity_anim.setStartValue(self.windowOpacity())
        self.opacity_anim.setEndValue(0.0)
        self.opacity_anim.finished.connect(self.hide)
        self.opacity_anim.start()

    def cleanup(self) -> None:
        if self.processing_thread and self.processing_thread.isRunning():
            self.processing_thread.wait(1000)
        for panel in (self._scheduler_panel, self._memory_panel):
            if panel:
                panel.close()
        self.close()

    def snapshot_state(self) -> dict:
        return {
            "messages": list(getattr(self.chat_widget, "history", [])),
            "input_text": self.input_field.text(),
            "visible": self.isVisible(),
            "geometry": self.geometry(),
            "ai_assistant": self.ai_assistant,
            "tts_callback": self.tts_callback,
        }

    def restore_state(self, state: dict) -> None:
        messages = state.get("messages", [])
        if messages:
            clear_layout(self.chat_widget.layout())
            self.chat_widget.history = []
        for item in messages:
            self.chat_widget.add_message(item.get("message", ""), is_user=bool(item.get("is_user", False)))
        self.input_field.setText(state.get("input_text", ""))
        if state.get("visible"):
            self.setGeometry(state.get("geometry", self.geometry()))
            self.show()
            self.activateWindow()
        self.scroll_to_bottom()

    def refresh_theme(self) -> None:
        state = self.snapshot_state()
        scheduler_visible = self._scheduler_panel.isVisible() if self._scheduler_panel else False
        memory_visible = self._memory_panel.isVisible() if self._memory_panel else False
        scheduler_pos = self._scheduler_panel.pos() if self._scheduler_panel else None
        memory_pos = self._memory_panel.pos() if self._memory_panel else None

        if self._scheduler_panel:
            self._scheduler_panel.refresh_theme()
            if scheduler_visible:
                self._scheduler_panel.move(scheduler_pos)
                self._scheduler_panel.show()
        if self._memory_panel:
            self._memory_panel.refresh_theme()
            if memory_visible:
                self._memory_panel.move(memory_pos)
                self._memory_panel.show()

        if hasattr(self, "_status_timer") and self._status_timer:
            self._status_timer.stop()
        if hasattr(self, "suggestion_bar") and self.suggestion_bar:
            self.suggestion_bar.stop_timer()
        clear_layout(self.centralWidget().layout())
        self._init_ui()
        self.restore_state(state)


# ── 팩토리 ───────────────────────────────────────────────────────────────────

def create_text_interface(ai_assistant=None, tts_callback=None) -> TextInterface:
    """TextInterface 인스턴스 생성 팩토리."""
    return TextInterface(ai_assistant, tts_callback)
