"""
말풍선 위젯 (원본 구현 기반)
"""
import os
import logging
import threading
from PySide6.QtWidgets import QWidget
from PySide6.QtCore import Qt, QRect, QPoint
from PySide6.QtGui import QPainter, QColor, QFont, QFontMetrics, QFontDatabase, QPolygon

from ui import theme as theme_module

_font_family = None  # 전역 폰트 패밀리 이름 캐시
_font_family_lock = threading.Lock()


def register_fonts():
    """애플리케이션 시작 시 폰트 등록 (메인 스레드에서 호출 권장)"""
    global _font_family
    if _font_family is not None:
        return _font_family

    with _font_family_lock:
        if _font_family is not None:
            return _font_family

        try:
            from core.resource_manager import ResourceManager
            font_path = ResourceManager.get_bundle_path("DNFBitBitv2.ttf")
        except Exception:
            font_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "DNFBitBitv2.ttf")

        if os.path.exists(font_path):
            font_id = QFontDatabase.addApplicationFont(font_path)
            if font_id != -1:
                families = QFontDatabase.applicationFontFamilies(font_id)
                if families:
                    _font_family = families[0]
                    logging.info(f"말풍선 폰트 로드 완료: {_font_family}")
        else:
            logging.warning(f"말풍선 폰트 파일을 찾지 못했습니다: {font_path}")

        if _font_family is None:
            _font_family = "맑은 고딕"
            logging.warning("말풍선 폰트를 기본값(맑은 고딕)으로 사용합니다.")

    return _font_family


class SpeechBubble(QWidget):
    """말풍선 위젯"""

    def __init__(self, text, parent):
        super().__init__(parent)
        self.text = text
        self.parent_widget = parent

        # 윈도우 설정
        self.setWindowFlags(Qt.ToolTip | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)

        # 폰트 설정 (이미 등록된 폰트 사용)
        font_family = register_fonts()
        self.font = QFont(font_family, theme_module.FONT_SIZE_LARGE + 1)
        self.fm = QFontMetrics(self.font)
        self.padding = 12

        try:
            # 크기 계산
            self.calculate_size()
            # 위치 계산
            self.update_position()
        except Exception as e:
            logging.error(f"SpeechBubble 초기화 중 오류: {e}")

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

        # 테마 기반 색상
        bg_color = QColor(theme_module.COLOR_BG_WHITE)
        bg_color.setAlpha(245)
        border_color = QColor(210, 210, 210)

        # 배경 그리기
        painter.setBrush(bg_color)
        painter.setPen(border_color)
        painter.drawRoundedRect(bubble_rect, 10, 10)

        # 꼬리 그리기
        tail_x = self.bubble_width // 2
        tail_y = bubble_rect.bottom()
        tail_points = [
            (tail_x - 8, tail_y),
            (tail_x, tail_y + 15),
            (tail_x + 8, tail_y)
        ]
        polygon = QPolygon([QPoint(x, y) for x, y in tail_points])
        painter.setBrush(bg_color)
        painter.setPen(border_color)
        painter.drawPolygon(polygon)

        # 텍스트 그리기
        painter.setPen(QColor(theme_module.COLOR_TEXT_PRIMARY))
        painter.setFont(self.font)
        text_rect = bubble_rect.adjusted(self.padding, self.padding, -self.padding, -self.padding)
        painter.drawText(text_rect, Qt.TextWordWrap | Qt.AlignCenter, self.text)
