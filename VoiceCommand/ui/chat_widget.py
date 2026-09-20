import logging
from datetime import datetime
from typing import Optional
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget
from ui.common import clear_layout
from ui.theme import (
    FONT_KO, FONT_SIZE_LARGE, FONT_SIZE_SMALL, SPACING_LG,
    COLOR_PRIMARY, COLOR_ACCENT, COLOR_MUTED_LIGHT, COLOR_TEXT_PRIMARY,
    COLOR_BG_CHAT_USER, COLOR_BG_CHAT_AARI,
)
from ui import theme as theme_module
from i18n.translator import _


try:
    from VoiceCommand import parse_emotion_text, EMOTION_EMOJI
except Exception as _e:
    logging.debug("VoiceCommand 임포트 건너뜀: %s", _e)
    parse_emotion_text = None
    EMOTION_EMOJI = {}

# ── 채팅 위젯 ────────────────────────────────────────────────────────────────

class ChatWidget(QFrame):
    """채팅 메시지를 표시하는 위젯. 최대 MAX_MESSAGES개 메시지 유지."""

    MAX_MESSAGES = 50
    MIN_BUBBLE_WIDTH = 220
    BUBBLE_SIDE_GAP = 56
    BUBBLE_WIDTH_RATIO = 0.78

    def __init__(self):
        super().__init__()
        self.history = []
        self.setFrameStyle(QFrame.StyledPanel)
        self.setStyleSheet("QFrame { background-color: transparent; border: none; }")
        lay = QVBoxLayout(self)
        lay.setAlignment(Qt.AlignTop)
        lay.setSpacing(SPACING_LG)
        lay.setContentsMargins(12, 12, 12, 12)

    def render_history(self) -> None:
        clear_layout(self.layout())
        for item in self.history[-self.MAX_MESSAGES:]:
            self._add_message_widget(item)

    def add_message(self, message: str, is_user: bool = True, timestamp: Optional[str] = None) -> None:
        self.history.append(
            {
                "message": message,
                "is_user": is_user,
                "timestamp": timestamp or datetime.now().strftime("%H:%M:%S"),
            }
        )
        if len(self.history) > self.MAX_MESSAGES:
            self.history = self.history[-self.MAX_MESSAGES:]
        self.render_history()

    def update_message(self, index: int, message: str) -> None:
        if 0 <= index < len(self.history):
            self.history[index]["message"] = message
            self.render_history()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self.history:
            self.render_history()

    def _bubble_max_width(self) -> int:
        layout = self.layout()
        contents = layout.contentsMargins()
        available = self.width() - contents.left() - contents.right() - self.BUBBLE_SIDE_GAP
        proportional = int(max(self.width(), self.MIN_BUBBLE_WIDTH) * self.BUBBLE_WIDTH_RATIO)
        return max(self.MIN_BUBBLE_WIDTH, min(available, proportional))

    def _add_message_widget(self, item: dict) -> None:
        message = str(item.get("message", ""))
        is_user = bool(item.get("is_user"))
        timestamp = str(item.get("timestamp") or datetime.now().strftime("%H:%M:%S"))
        display_message = message
        if not is_user and parse_emotion_text:
            emotion, pure_text = parse_emotion_text(message)
            emoji = EMOTION_EMOJI.get(emotion, "")
            if pure_text:
                display_message = f"{emoji} {pure_text}".strip() if emoji else pure_text

        sender_name  = _("나") if is_user else _("아리")
        sender_color = COLOR_PRIMARY if is_user else COLOR_ACCENT
        bg_color     = COLOR_BG_CHAT_USER if is_user else COLOR_BG_CHAT_AARI
        corner_style = "border-top-right-radius: 0px;" if is_user else "border-top-left-radius: 0px;"

        msg_frame = QFrame()
        msg_frame.setObjectName("chatMessageBubble")
        msg_frame.setMaximumWidth(self._bubble_max_width())
        msg_frame.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        msg_lay = QVBoxLayout(msg_frame)
        msg_lay.setContentsMargins(15, 10, 15, 10)

        sender_lbl = QLabel(sender_name)
        sender_lbl.setFont(QFont(FONT_KO, FONT_SIZE_SMALL + 1, QFont.Bold))
        sender_lbl.setStyleSheet(f"color: {sender_color};")
        sender_lbl.setWordWrap(True)
        sender_lbl.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        sender_lbl.setMinimumWidth(0)

        msg_lbl = QLabel(display_message)
        msg_lbl.setWordWrap(True)
        msg_lbl.setFont(QFont(FONT_KO, FONT_SIZE_LARGE))
        msg_lbl.setStyleSheet(f"color: {COLOR_TEXT_PRIMARY}; margin: 2px 0px;")
        msg_lbl.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        msg_lbl.setMinimumWidth(0)

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
        row_widget = QWidget()
        row_widget.setObjectName("chatMessageRow")
        row_layout = QHBoxLayout(row_widget)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(0)
        if is_user:
            row_layout.addStretch()
            row_layout.addWidget(msg_frame)
        else:
            row_layout.addWidget(msg_frame)
            row_layout.addStretch()
        self.layout().addWidget(row_widget)

    def refresh_theme(self) -> None:
        self.layout().setSpacing(theme_module.SPACING_LG)
        self.render_history()


