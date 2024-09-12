import sys
import threading
import logging
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QTextEdit, QLineEdit, QPushButton, QLabel, QScrollArea,
    QFrame, QCheckBox, QMenuBar, QStatusBar, QSplitter
)
from PySide6.QtCore import Qt, QThread, Signal, QTimer
from PySide6.QtGui import QFont, QTextCursor, QPixmap, QIcon
from datetime import datetime
import json
import os


class ChatWidget(QFrame):
    """채팅 메시지를 표시하는 위젯"""
    
    def __init__(self):
        super().__init__()
        self.setFrameStyle(QFrame.StyledPanel)
        self.setStyleSheet("""
            QFrame {
                background-color: #f0f0f0;
                border-radius: 10px;
                margin: 5px;
                padding: 10px;
            }
        """)
        
        layout = QVBoxLayout()
        self.setLayout(layout)
        
    def add_message(self, message, is_user=True):
        """메시지 추가"""
        timestamp = datetime.now().strftime("%H:%M:%S")
        
        # 메시지 컨테이너
        msg_frame = QFrame()
        msg_layout = QVBoxLayout(msg_frame)
        
        # 사용자/AI 구분
        sender_label = QLabel("사용자" if is_user else "아리")
        sender_label.setFont(QFont("맑은 고딕", 9, QFont.Bold))
        sender_label.setStyleSheet(f"color: {'#0066cc' if is_user else '#cc6600'};")
        
        # 메시지 내용
        message_label = QLabel(message)
        message_label.setWordWrap(True)
        message_label.setFont(QFont("맑은 고딕", 10))
        message_label.setStyleSheet("color: #333333; margin: 5px 0px;")
        
        # 시간
        time_label = QLabel(timestamp)
        time_label.setFont(QFont("맑은 고딕", 8))
        time_label.setStyleSheet("color: #888888;")
        time_label.setAlignment(Qt.AlignRight)
        
        msg_layout.addWidget(sender_label)
        msg_layout.addWidget(message_label)
        msg_layout.addWidget(time_label)
        
        # 사용자 메시지는 오른쪽 정렬
        if is_user:
            msg_frame.setStyleSheet("""
                QFrame {
                    background-color: #e3f2fd;
                    border-radius: 10px;
                    margin: 5px 50px 5px 5px;
                    padding: 10px;
                }
            """)
        else:
            msg_frame.setStyleSheet("""
                QFrame {
                    background-color: #fff3e0;
                    border-radius: 10px;
                    margin: 5px 5px 5px 50px;
                    padding: 10px;
                }
            """)
        
        self.layout().addWidget(msg_frame)


class TextInterfaceThread(QThread):
    """텍스트 처리를 위한 별도 스레드"""
    response_ready = Signal(str)
    
    def __init__(self, ai_assistant):
        super().__init__()
        self.ai_assistant = ai_assistant
        self.query = ""
        
    def set_query(self, query):
        self.query = query
        
    def run(self):
        try:
            response, entities, sentiment = self.ai_assistant.process_text_input(self.query)
            self.response_ready.emit(response)
        except Exception as e:
            logging.error(f"텍스트 처리 중 오류: {e}")
            self.response_ready.emit("죄송합니다. 처리 중 오류가 발생했습니다.")


class TextInterface(QMainWindow):
    """텍스트 입력 인터페이스"""
    
    def __init__(self, ai_assistant=None):
        super().__init__()
        self.ai_assistant = ai_assistant
        self.processing_thread = None
        
        self.init_ui()
        self.load_chat_history()
        
    def init_ui(self):
        """UI 초기화"""
        self.setWindowTitle("아리 - 텍스트 채팅")
        self.setGeometry(100, 100, 800, 600)
        
        # 중앙 위젯
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        # 메인 레이아웃
        main_layout = QVBoxLayout(central_widget)
        
        # 상단 패널
        top_panel = self.create_top_panel()
        main_layout.addWidget(top_panel)
        
        # 스플리터로 채팅창과 설정 분리
        splitter = QSplitter(Qt.Horizontal)
        main_layout.addWidget(splitter)
        
        # 채팅 영역
        chat_area = self.create_chat_area()
        splitter.addWidget(chat_area)
        
        # 설정 패널
        settings_panel = self.create_settings_panel()
        splitter.addWidget(settings_panel)
        
        # 초기 크기 비율 설정
        splitter.setSizes([600, 200])
        
        # 하단 입력 영역
        input_area = self.create_input_area()
        main_layout.addWidget(input_area)
        
        # 상태바
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("준비 완료")
        
        # 스타일 적용
        self.apply_styles()
        
    def create_top_panel(self):
        """상단 패널 생성"""
        panel = QFrame()
        panel.setFixedHeight(60)
        panel.setStyleSheet("""
            QFrame {
                background-color: #2196f3;
                border-radius: 5px;
            }
        """)
        
        layout = QHBoxLayout(panel)
        
        # 제목
        title = QLabel("아리 AI 어시스턴트")
        title.setFont(QFont("맑은 고딕", 16, QFont.Bold))
        title.setStyleSheet("color: white; padding: 10px;")
        layout.addWidget(title)
        
        layout.addStretch()
        
        # 연결 상태
        self.connection_label = QLabel("● 연결됨")
        self.connection_label.setStyleSheet("color: #4caf50; font-weight: bold; padding: 10px;")
        layout.addWidget(self.connection_label)
        
        return panel
        
    def create_chat_area(self):
        """채팅 영역 생성"""
        # 스크롤 영역
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setStyleSheet("""
            QScrollArea {
                border: 1px solid #cccccc;
                border-radius: 5px;
                background-color: white;
            }
        """)
        
        # 채팅 위젯
        self.chat_widget = ChatWidget()
        scroll_area.setWidget(self.chat_widget)
        
        return scroll_area
        
    def create_settings_panel(self):
        """설정 패널 생성"""
        panel = QFrame()
        panel.setStyleSheet("""
            QFrame {
                border: 1px solid #cccccc;
                border-radius: 5px;
                background-color: #fafafa;
            }
        """)
        
        layout = QVBoxLayout(panel)
        
        # 제목
        title = QLabel("설정")
        title.setFont(QFont("맑은 고딕", 12, QFont.Bold))
        layout.addWidget(title)
        
        # 자동 학습 설정
        self.auto_learning_checkbox = QCheckBox("자동 학습 활성화")
        self.auto_learning_checkbox.setChecked(True)
        self.auto_learning_checkbox.stateChanged.connect(self.toggle_auto_learning)
        layout.addWidget(self.auto_learning_checkbox)
        
        # 학습 상태
        self.learning_status_label = QLabel("학습 상태: 대기 중")
        self.learning_status_label.setStyleSheet("color: #666666; font-size: 10px;")
        layout.addWidget(self.learning_status_label)
        
        layout.addStretch()
        
        # 버튼들
        clear_btn = QPushButton("채팅 기록 삭제")
        clear_btn.clicked.connect(self.clear_chat)
        layout.addWidget(clear_btn)
        
        save_btn = QPushButton("대화 내용 저장")
        save_btn.clicked.connect(self.save_chat)
        layout.addWidget(save_btn)
        
        return panel
        
    def create_input_area(self):
        """입력 영역 생성"""
        frame = QFrame()
        frame.setFixedHeight(80)
        frame.setStyleSheet("""
            QFrame {
                border: 1px solid #cccccc;
                border-radius: 5px;
                background-color: white;
            }
        """)
        
        layout = QHBoxLayout(frame)
        
        # 텍스트 입력
        self.input_field = QLineEdit()
        self.input_field.setPlaceholderText("메시지를 입력하세요... (예: '안녕하세요', '학습: 인공지능')")
        self.input_field.setFont(QFont("맑은 고딕", 11))
        self.input_field.returnPressed.connect(self.send_message)
        layout.addWidget(self.input_field)
        
        # 전송 버튼
        send_btn = QPushButton("전송")
        send_btn.setFixedSize(80, 40)
        send_btn.clicked.connect(self.send_message)
        send_btn.setStyleSheet("""
            QPushButton {
                background-color: #2196f3;
                color: white;
                border-radius: 5px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #1976d2;
            }
        """)
        layout.addWidget(send_btn)
        
        return frame
        
    def apply_styles(self):
        """전체 스타일 적용"""
        self.setStyleSheet("""
            QMainWindow {
                background-color: #f5f5f5;
            }
            QPushButton {
                padding: 5px 10px;
                border-radius: 3px;
                border: 1px solid #cccccc;
                background-color: white;
            }
            QPushButton:hover {
                background-color: #e0e0e0;
            }
            QCheckBox {
                font-size: 11px;
                padding: 5px;
            }
        """)
        
    def send_message(self):
        """메시지 전송"""
        message = self.input_field.text().strip()
        if not message:
            return
            
        # 사용자 메시지 표시
        self.chat_widget.add_message(message, is_user=True)
        self.input_field.clear()
        
        # 상태 업데이트
        self.status_bar.showMessage("처리 중...")
        
        # AI 응답 처리
        if self.ai_assistant:
            self.processing_thread = TextInterfaceThread(self.ai_assistant)
            self.processing_thread.response_ready.connect(self.handle_response)
            self.processing_thread.set_query(message)
            self.processing_thread.start()
        else:
            self.handle_response("AI 어시스턴트가 연결되지 않았습니다.")
            
    def handle_response(self, response):
        """AI 응답 처리"""
        self.chat_widget.add_message(response, is_user=False)
        self.status_bar.showMessage("준비 완료")
        
        # 스크롤을 아래로 이동
        self.scroll_to_bottom()
        
        # 채팅 기록 저장
        self.save_chat_history()
        
    def scroll_to_bottom(self):
        """채팅창을 가장 아래로 스크롤"""
        scroll_area = self.centralWidget().findChild(QScrollArea)
        if scroll_area:
            scroll_bar = scroll_area.verticalScrollBar()
            scroll_bar.setValue(scroll_bar.maximum())
            
    def toggle_auto_learning(self, state):
        """자동 학습 토글"""
        if self.ai_assistant:
            if state == Qt.Checked:
                self.ai_assistant.enable_auto_learning()
                self.learning_status_label.setText("학습 상태: 활성화됨")
            else:
                self.ai_assistant.disable_auto_learning()
                self.learning_status_label.setText("학습 상태: 비활성화됨")
                
    def clear_chat(self):
        """채팅 기록 삭제"""
        # 기존 위젯들 제거
        layout = self.chat_widget.layout()
        while layout.count():
            child = layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()
                
    def save_chat(self):
        """대화 내용 저장"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"chat_history_{timestamp}.txt"
        
        try:
            with open(filename, 'w', encoding='utf-8') as f:
                f.write(f"아리 채팅 기록 - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write("=" * 50 + "\n\n")
                
                # 채팅 위젯에서 메시지 추출 (실제 구현에서는 더 정교한 방법 필요)
                f.write("채팅 내용이 저장되었습니다.\n")
                
            self.status_bar.showMessage(f"대화 내용이 {filename}에 저장되었습니다.")
        except Exception as e:
            logging.error(f"채팅 저장 중 오류: {e}")
            self.status_bar.showMessage("저장 중 오류가 발생했습니다.")
            
    def save_chat_history(self):
        """채팅 기록 저장 (자동)"""
        # 간단한 자동 저장 구현
        pass
        
    def load_chat_history(self):
        """채팅 기록 로드"""
        # 이전 채팅 기록 로드 구현
        pass
        
    def set_ai_assistant(self, ai_assistant):
        """AI 어시스턴트 설정"""
        self.ai_assistant = ai_assistant
        if ai_assistant:
            self.connection_label.setText("● 연결됨")
            self.connection_label.setStyleSheet("color: #4caf50; font-weight: bold; padding: 10px;")
        else:
            self.connection_label.setText("● 연결 끊김")
            self.connection_label.setStyleSheet("color: #f44336; font-weight: bold; padding: 10px;")


def create_text_interface(ai_assistant=None):
    """텍스트 인터페이스 생성 함수"""
    return TextInterface(ai_assistant)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    
    # 테스트용
    window = TextInterface()
    window.show()
    
    sys.exit(app.exec()) 