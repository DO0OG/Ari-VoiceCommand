"""
말풍선 위젯 (원본 구현 기반)
"""
import os
from PySide6.QtWidgets import QWidget
from PySide6.QtCore import Qt, QRect, QTimer
from PySide6.QtGui import QPainter, QColor, QFont, QFontMetrics, QFontDatabase


class SpeechBubble(QWidget):
    """말풍선 위젯"""

    def __init__(self, text, parent):
        super().__init__(parent)
        self.text = text
        self.parent_widget = parent

        # 윈도우 설정
        self.setWindowFlags(Qt.ToolTip | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)

        # 폰트 설정
        font_path = os.path.join(os.path.dirname(__file__), "DNFBitBitv2.ttf")
        if os.path.exists(font_path):
            font_id = QFontDatabase.addApplicationFont(font_path)
            if font_id != -1:
                font_family = QFontDatabase.applicationFontFamilies(font_id)[0]
                self.font = QFont(font_family, 11)
            else:
                self.font = QFont("맑은 고딕", 10)
        else:
            self.font = QFont("맑은 고딕", 10)

        self.fm = QFontMetrics(self.font)
        self.padding = 12

        # 크기 계산
        self.calculate_size()

        # 위치 계산 및 표시
        self.update_position()
        self.show()
        self.raise_()

    def calculate_size(self):
        """말풍선 크기 계산"""
        max_width = 250
        text_width = self.fm.horizontalAdvance(self.text)

        if text_width <= max_width:
            # 한 줄
            self.bubble_width = text_width + self.padding * 2
            self.bubble_height = self.fm.height() + self.padding * 2
        else:
            # 여러 줄
            self.bubble_width = max_width
            rect = self.fm.boundingRect(
                QRect(0, 0, max_width - self.padding * 2, 1000),
                Qt.TextWordWrap,
                self.text
            )
            self.bubble_height = rect.height() + self.padding * 2

        # 꼬리 공간 추가
        self.bubble_height += 15

        self.setFixedSize(self.bubble_width, self.bubble_height)

    def update_position(self):
        """말풍선 위치 업데이트"""
        if not self.parent_widget:
            return

        # 캐릭터의 화면 좌표
        parent_rect = self.parent_widget.rect()
        parent_pos = self.parent_widget.mapToGlobal(parent_rect.topLeft())

        # 가로 중앙 정렬
        x = parent_pos.x() + (parent_rect.width() - self.bubble_width) // 2

        # 캐릭터 위쪽에 표시 (15px 간격)
        y = parent_pos.y() - self.bubble_height - 15

        # 화면 경계 체크
        y = max(10, y)

        self.move(x, y)

    def paintEvent(self, event):
        """말풍선 그리기"""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        # 말풍선 영역 (꼬리 제외)
        bubble_rect = QRect(0, 0, self.bubble_width, self.bubble_height - 15)

        # 배경 그리기
        painter.setBrush(QColor(255, 255, 255, 240))
        painter.setPen(QColor(200, 200, 200))
        painter.drawRoundedRect(bubble_rect, 10, 10)

        # 꼬리 그리기
        tail_x = self.bubble_width // 2
        tail_y = bubble_rect.bottom()
        tail_points = [
            (tail_x - 8, tail_y),
            (tail_x, tail_y + 15),
            (tail_x + 8, tail_y)
        ]
        from PySide6.QtGui import QPolygon
        from PySide6.QtCore import QPoint
        polygon = QPolygon([QPoint(x, y) for x, y in tail_points])
        painter.setBrush(QColor(255, 255, 255, 240))
        painter.setPen(QColor(200, 200, 200))
        painter.drawPolygon(polygon)

        # 텍스트 그리기
        painter.setPen(QColor(51, 51, 51))
        painter.setFont(self.font)
        text_rect = bubble_rect.adjusted(self.padding, self.padding, -self.padding, -self.padding)
        painter.drawText(text_rect, Qt.TextWordWrap | Qt.AlignCenter, self.text)
