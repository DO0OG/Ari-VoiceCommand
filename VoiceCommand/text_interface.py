import sys
import threading
import logging
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLineEdit, QPushButton, QLabel, QScrollArea,
    QFrame, QGraphicsDropShadowEffect
)
from PySide6.QtCore import Qt, QThread, Signal, QTimer, QPropertyAnimation, QEasingCurve, QRect
from PySide6.QtGui import QFont
from datetime import datetime

class ChatWidget(QFrame):
    """채팅 메시지를 표시하는 위젯. 메모리 관리를 위해 오래된 메시지를 삭제합니다."""
    def __init__(self):
        super().__init__()
        self.max_messages = 50  # 메모리 최적화를 위한 최대 메시지 유지 개수
        self.setFrameStyle(QFrame.StyledPanel)
        self.setStyleSheet("QFrame { background-color: transparent; border: none; }")
        
        layout = QVBoxLayout()
        layout.setAlignment(Qt.AlignTop)
        layout.setSpacing(10)
        self.setLayout(layout)
        
    def add_message(self, message, is_user=True):
        # 메시지 개수 제한 체크 및 오래된 메시지 삭제
        while self.layout().count() >= self.max_messages:
            item = self.layout().takeAt(0)
            if item and item.widget():
                item.widget().deleteLater()

        timestamp = datetime.now().strftime("%H:%M:%S")
        
        msg_frame = QFrame()
        msg_layout = QVBoxLayout(msg_frame)
        msg_layout.setContentsMargins(15, 10, 15, 10)
        
        sender_name = "나" if is_user else "아리"
        sender_color = "#4a90e2" if is_user else "#ff7b54"
        bg_color = "#e3f2fd" if is_user else "#fff3e0"
        radius_style = "border-top-right-radius: 0px; margin-left: 40px;" if is_user else "border-top-left-radius: 0px; margin-right: 40px;"
        
        sender_label = QLabel(sender_name)
        sender_label.setFont(QFont("맑은 고딕", 9, QFont.Bold))
        sender_label.setStyleSheet(f"color: {sender_color};")
        
        message_label = QLabel(message)
        message_label.setWordWrap(True)
        message_label.setFont(QFont("맑은 고딕", 10))
        message_label.setStyleSheet("color: #333333; margin: 2px 0px;")
        
        time_label = QLabel(timestamp)
        time_label.setFont(QFont("맑은 고딕", 8))
        time_label.setStyleSheet("color: #aaaaaa;")
        time_label.setAlignment(Qt.AlignRight)
        
        msg_layout.addWidget(sender_label)
        msg_layout.addWidget(message_label)
        msg_layout.addWidget(time_label)
        
        msg_frame.setStyleSheet(f"""
            QFrame {{
                background-color: {bg_color};
                border-radius: 12px;
                {radius_style}
            }}
        """)
        
        self.layout().addWidget(msg_frame)


class TextInterfaceThread(QThread):
    """비동기 AI 응답 처리를 위한 스레드"""
    response_ready = Signal(str)
    
    def __init__(self, ai_assistant, query):
        super().__init__()
        self.ai_assistant = ai_assistant
        self.query = query
        
    def run(self):
        try:
            # 표준 인터페이스 process_query 사용
            if hasattr(self.ai_assistant, 'process_query'):
                response, _, _ = self.ai_assistant.process_query(self.query)
            elif hasattr(self.ai_assistant, 'chat'):
                response = self.ai_assistant.chat(self.query)
            else:
                response = "죄송합니다. AI 응답 엔진을 초기화할 수 없습니다."
            
            self.response_ready.emit(str(response))
        except Exception as e:
            logging.error(f"텍스트 처리 오류: {e}")
            self.response_ready.emit(f"오류가 발생했습니다: {e}")


class TitleBar(QFrame):
    """커스텀 타이틀 바 (드래그 이동 지원)"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent_window = parent
        self.setFixedHeight(40)
        self.setStyleSheet("""
            QFrame {
                background-color: #2c3e50;
                border-top-left-radius: 15px;
                border-top-right-radius: 15px;
            }
        """)
        
        layout = QHBoxLayout(self)
        layout.setContentsMargins(15, 0, 10, 0)
        
        title = QLabel("💬 아리와 대화하기")
        title.setFont(QFont("맑은 고딕", 11, QFont.Bold))
        title.setStyleSheet("color: white;")
        layout.addWidget(title)
        
        layout.addStretch()
        
        self.close_btn = QPushButton("✕")
        self.close_btn.setFixedSize(30, 30)
        self.close_btn.setCursor(Qt.PointingHandCursor)
        self.close_btn.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                color: white;
                font-weight: bold;
                border: none;
                border-radius: 15px;
            }
            QPushButton:hover { background-color: #e74c3c; }
        """)
        self.close_btn.clicked.connect(self.parent_window.close_with_animation)
        layout.addWidget(self.close_btn)
        
        self.drag_pos = None

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.drag_pos = event.globalPos() - self.parent_window.pos()
            event.accept()

    def mouseMoveEvent(self, event):
        if event.buttons() == Qt.LeftButton and self.drag_pos:
            self.parent_window.move(event.globalPos() - self.drag_pos)
            event.accept()


class TextInterface(QMainWindow):
    """말풍선 확장형 텍스트 인터페이스 메인 창"""
    def __init__(self, ai_assistant=None, tts_callback=None):
        super().__init__()
        self.ai_assistant = ai_assistant
        self.tts_callback = tts_callback
        self.processing_thread = None
        
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        
        self.init_ui()
        self.init_animations()
        
    def init_ui(self):
        self.resize(380, 550)
        
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(10, 10, 10, 10)
        
        self.bg_frame = QFrame()
        self.bg_frame.setObjectName("BgFrame")
        self.bg_frame.setStyleSheet("""
            #BgFrame {
                background-color: rgba(250, 250, 252, 245);
                border-radius: 15px;
                border: 1px solid rgba(200, 200, 200, 100);
            }
        """)
        
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(15)
        shadow.setColor(Qt.black)
        shadow.setOffset(0, 5)
        self.bg_frame.setGraphicsEffect(shadow)
        
        bg_layout = QVBoxLayout(self.bg_frame)
        bg_layout.setContentsMargins(0, 0, 0, 0)
        bg_layout.setSpacing(0)
        main_layout.addWidget(self.bg_frame)
        
        self.title_bar = TitleBar(self)
        bg_layout.addWidget(self.title_bar)
        
        # 채팅 영역 (스크롤)
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setStyleSheet("""
            QScrollArea { border: none; background-color: transparent; }
            QScrollBar:vertical { border: none; background: #f0f0f0; width: 8px; border-radius: 4px; }
            QScrollBar::handle:vertical { background: #cccccc; border-radius: 4px; }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { border: none; background: none; }
        """)
        
        self.chat_widget = ChatWidget()
        self.scroll_area.setWidget(self.chat_widget)
        bg_layout.addWidget(self.scroll_area)
        
        # 입력 영역
        input_frame = QFrame()
        input_frame.setFixedHeight(70)
        input_frame.setStyleSheet("""
            QFrame {
                background-color: white;
                border-bottom-left-radius: 15px;
                border-bottom-right-radius: 15px;
                border-top: 1px solid #eeeeee;
            }
        """)
        
        input_layout = QHBoxLayout(input_frame)
        input_layout.setContentsMargins(15, 10, 15, 15)
        input_layout.setSpacing(10)
        
        self.input_field = QLineEdit()
        self.input_field.setPlaceholderText("메시지 입력...")
        self.input_field.setFont(QFont("맑은 고딕", 10))
        self.input_field.setStyleSheet("""
            QLineEdit {
                border: 1px solid #e0e0e0; border-radius: 18px; padding: 0 15px; background-color: #f8f9fa;
            }
            QLineEdit:focus { border: 1px solid #4a90e2; background-color: white; }
        """)
        self.input_field.returnPressed.connect(self.send_message)
        input_layout.addWidget(self.input_field)
        
        self.send_btn = QPushButton("➤")
        self.send_btn.setFixedSize(36, 36)
        self.send_btn.setCursor(Qt.PointingHandCursor)
        self.send_btn.setStyleSheet("""
            QPushButton {
                background-color: #4a90e2; color: white; border-radius: 18px; font-weight: bold; font-size: 16px;
            }
            QPushButton:hover { background-color: #357abd; }
            QPushButton:disabled { background-color: #cccccc; }
        """)
        self.send_btn.clicked.connect(self.send_message)
        input_layout.addWidget(self.send_btn)
        
        bg_layout.addWidget(input_frame)
        
        # 초기 메시지
        self.chat_widget.add_message("안녕하세요! 무엇을 도와드릴까요?", is_user=False)

    def init_animations(self):
        """애니메이션 객체 초기화"""
        self.anim = QPropertyAnimation(self, b"geometry")
        self.anim.setDuration(300)
        self.anim.setEasingCurve(QEasingCurve.OutBack)
        
        self.opacity_anim = QPropertyAnimation(self, b"windowOpacity")
        self.opacity_anim.setDuration(250)

    def send_message(self):
        """사용자 메시지 전송 및 AI 응답 요청"""
        query = self.input_field.text().strip()
        if not query or (self.processing_thread and self.processing_thread.isRunning()):
            return
            
        self.chat_widget.add_message(query, is_user=True)
        self.input_field.clear()
        self.set_ui_enabled(False)
        self.scroll_to_bottom()
        
        if self.ai_assistant:
            self.processing_thread = TextInterfaceThread(self.ai_assistant, query)
            self.processing_thread.response_ready.connect(self.handle_response)
            self.processing_thread.finished.connect(lambda: self.set_ui_enabled(True))
            self.processing_thread.start()
        else:
            self.handle_response("AI 엔진이 연결되지 않았습니다.")
            self.set_ui_enabled(True)
            
    def set_ui_enabled(self, enabled):
        """입력 인터페이스 활성화/비활성화"""
        self.input_field.setEnabled(enabled)
        self.send_btn.setEnabled(enabled)
        if enabled:
            self.input_field.setFocus()

    def handle_response(self, response):
        """AI 응답을 UI에 표시하고 TTS를 재생"""
        self.chat_widget.add_message(response, is_user=False)
        self.scroll_to_bottom()
        if self.tts_callback:
            self.tts_callback(response)
            
    def scroll_to_bottom(self):
        """채팅 영역을 가장 아래로 스크롤"""
        QTimer.singleShot(50, lambda: self.scroll_area.verticalScrollBar().setValue(
            self.scroll_area.verticalScrollBar().maximum()))
            
    def show_near(self, target_x, target_y, target_width=0, target_height=0):
        """타겟 좌표 인근에 팝업 애니메이션과 함께 표시"""
        screen = QApplication.primaryScreen().geometry()
        
        # 최적 팝업 위치 계산 (화면 경계 고려)
        final_x = target_x + target_width + 10
        final_y = target_y + target_height // 2 - self.height() // 2
        
        if final_x + self.width() > screen.width():
            final_x = target_x - self.width() - 10
        final_y = max(20, min(final_y, screen.height() - self.height() - 40))
            
        start_rect = QRect(target_x + target_width//2, target_y + target_height//2, 1, 1)
        end_rect = QRect(final_x, final_y, self.width(), self.height())
        
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
        
    def close_with_animation(self):
        """부드럽게 사라지는 애니메이션과 함께 숨김"""
        self.anim.stop()
        start_rect = self.geometry()
        end_rect = QRect(start_rect.x(), start_rect.y() + 30, start_rect.width(), start_rect.height())
        
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

    def cleanup(self):
        """자원 정리"""
        if self.processing_thread and self.processing_thread.isRunning():
            self.processing_thread.wait(1000)
        self.close()

def create_text_interface(ai_assistant=None, tts_callback=None):
    """텍스트 인터페이스 생성을 위한 팩토리 함수"""
    return TextInterface(ai_assistant, tts_callback)
