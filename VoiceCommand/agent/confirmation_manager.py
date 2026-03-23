"""
확인 다이얼로그 관리자 (Confirmation Manager)
위험한 명령 실행 전 사용자 확인을 요청합니다.
크로스-스레드 안전한 Qt 다이얼로그를 제공합니다.
"""
import threading
import logging
from typing import Callable, Optional

from PySide6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame
from PySide6.QtCore import Qt, QTimer, Signal, QObject
from PySide6.QtGui import QFont

from agent.safety_checker import SafetyReport


class ConfirmationDialog(QDialog):
    """위험 작업 확인 다이얼로그 (15초 자동 취소)"""

    COUNTDOWN_SECONDS = 15

    def __init__(self, action_desc: str, report: SafetyReport, parent=None):
        super().__init__(parent)
        self._confirmed = False
        self._remaining = self.COUNTDOWN_SECONDS

        self.setWindowTitle("⚠️ 위험한 작업 확인")
        self.setWindowFlags(
            Qt.WindowStaysOnTopHint | Qt.Dialog
        )
        self.setMinimumWidth(420)
        self.setModal(True)

        self._build_ui(action_desc, report)

        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._tick)
        self._timer.start()

    def _build_ui(self, action_desc: str, report: SafetyReport):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(20, 20, 20, 20)

        # 경고 헤더
        header = QLabel("⚠️  위험한 작업이 감지되었습니다")
        font = QFont()
        font.setPointSize(12)
        font.setBold(True)
        header.setFont(font)
        header.setStyleSheet("color: #d32f2f;")
        layout.addWidget(header)

        # 구분선
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setFrameShadow(QFrame.Sunken)
        layout.addWidget(line)

        # 작업 설명
        desc_label = QLabel(f"<b>요청된 작업:</b><br>{action_desc}")
        desc_label.setWordWrap(True)
        layout.addWidget(desc_label)

        # 감지된 패턴
        if report.matched_patterns:
            patterns_items = "".join([f"<li>{p}</li>" for p in report.matched_patterns])
            patterns_html = f"<ul style='margin-top: 4px; margin-bottom: 4px; padding-left: 20px;'>{patterns_items}</ul>"
            pattern_label = QLabel(f"<b>감지된 위험 항목:</b><br>{patterns_html}")
            pattern_label.setWordWrap(True)
            pattern_label.setStyleSheet("color: #b71c1c; background: #fff3f3; padding: 8px; border-radius: 4px; font-size: 13px;")
            layout.addWidget(pattern_label)

        # 요약
        summary_label = QLabel(f"<i>{report.summary_kr}</i>")
        summary_label.setStyleSheet("color: #555;")
        layout.addWidget(summary_label)

        layout.addSpacing(8)

        # 버튼 영역
        btn_layout = QHBoxLayout()

        self._cancel_btn = QPushButton("취소")
        self._cancel_btn.setStyleSheet(
            "QPushButton { background: #e0e0e0; padding: 8px 24px; border-radius: 4px; font-size: 13px; }"
            "QPushButton:hover { background: #bdbdbd; }"
        )
        self._cancel_btn.clicked.connect(self._on_cancel)

        self._confirm_btn = QPushButton(f"실행 ({self.COUNTDOWN_SECONDS}초)")
        self._confirm_btn.setStyleSheet(
            "QPushButton { background: #d32f2f; color: white; padding: 8px 24px; border-radius: 4px; font-size: 13px; }"
            "QPushButton:hover { background: #b71c1c; }"
        )
        self._confirm_btn.clicked.connect(self._on_confirm)

        btn_layout.addWidget(self._cancel_btn)
        btn_layout.addStretch()
        btn_layout.addWidget(self._confirm_btn)
        layout.addLayout(btn_layout)

    def _tick(self):
        self._remaining -= 1
        self._confirm_btn.setText(f"실행 ({self._remaining}초)")
        if self._remaining <= 0:
            self._timer.stop()
            self._confirmed = False
            self.reject()

    def _on_confirm(self):
        self._timer.stop()
        self._confirmed = True
        self.accept()

    def _on_cancel(self):
        self._timer.stop()
        self._confirmed = False
        self.reject()

    @property
    def confirmed(self) -> bool:
        return self._confirmed


class _Bridge(QObject):
    """크로스-스레드 Signal 브릿지"""
    # holder: {"event": threading.Event, "result": bool} — 호출별 독립 객체로 경쟁 조건 방지
    request_dialog = Signal(str, object, object)  # action_desc, report, holder


class ConfirmationManager:
    """비-UI 스레드에서 확인 다이얼로그를 요청하는 매니저"""

    def __init__(self):
        self._bridge = _Bridge()
        self._bridge.request_dialog.connect(self._show_dialog_on_main_thread)

    def _show_dialog_on_main_thread(self, action_desc: str, report: SafetyReport, holder: dict):
        """메인 스레드에서 실행됨. 결과는 holder["result"]에 기록."""
        try:
            dialog = ConfirmationDialog(action_desc, report)
            dialog.exec()
            holder["result"] = dialog.confirmed
        except Exception as e:
            logging.error(f"확인 다이얼로그 오류: {e}")
            holder["result"] = False
        finally:
            holder["event"].set()

    def request_confirmation(
        self,
        action_desc: str,
        report: SafetyReport,
        tts_func: Optional[Callable] = None,
    ) -> bool:
        """
        CommandExecutionThread(비-UI)에서 호출 — 블로킹.
        메인 스레드에서 다이얼로그를 열고, threading.Event로 결과를 동기화합니다.
        timeout=20초 후 자동 취소.
        holder 딕셔너리를 호출별로 생성하여 self._result 공유 변수 경쟁 조건을 방지합니다.
        """
        if tts_func:
            try:
                tts_func(f"위험한 작업이 감지됐어요. {report.summary_kr}. 실행할까요?")
            except Exception as e:
                logging.debug(f"확인 안내 TTS 실패: {e}")

        holder: dict = {"event": threading.Event(), "result": False}
        self._bridge.request_dialog.emit(action_desc, report, holder)

        confirmed = holder["event"].wait(timeout=20)
        if not confirmed:
            logging.warning("확인 다이얼로그 timeout (20초)")
            return False

        return bool(holder["result"])


_manager_instance: Optional[ConfirmationManager] = None


def get_confirmation_manager() -> ConfirmationManager:
    global _manager_instance
    if _manager_instance is None:
        _manager_instance = ConfirmationManager()
    return _manager_instance
