"""
말풍선 위젯 (원본 구현 기반)
"""
import os
import logging
import re
import threading
from PySide6.QtWidgets import QWidget
from PySide6.QtCore import Qt, QRect, QPoint
from PySide6.QtGui import QPainter, QColor, QFont, QFontMetrics, QFontDatabase, QPolygon

from ui import theme as theme_module

_MARKDOWN_MARKS = re.compile(r"\*\*|__|`+|^\s{0,3}#{1,6}\s+", re.MULTILINE)


def _plain_bubble_text(text: str) -> str:
    """말풍선에는 마크다운 강조·제목·코드 기호를 빼고 보여 준다."""
    return _MARKDOWN_MARKS.sub("", text or "")


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

    MAX_LINES = 8

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

    def _text_height(self, text: str, width: int) -> int:
        # 그리기와 같은 폭·flags로 높이를 잰다
        return self.fm.boundingRect(
            QRect(0, 0, width, 100000),
            Qt.TextWordWrap | Qt.AlignCenter,
            text,
        ).height()

    def _fit_tail(self, text: str, width: int, max_height: int) -> str:
        """넘치는 긴 응답은 앞부분을 줄이고 최신 내용을 남긴다."""
        if self._text_height(text, width) <= max_height:
            return text
        low, high = 1, len(text)
        while low < high:
            middle = (low + high) // 2
            if self._text_height("…" + text[middle:].lstrip(), width) <= max_height:
                high = middle
            else:
                low = middle + 1
        return "…" + text[low:].lstrip()

    def calculate_size(self):
        """말풍선 크기 계산"""
        max_width = 250
        plain_text = _plain_bubble_text(self.text)
        # 개행이 있어도 가장 긴 줄 기준으로 폭을 정한다
        text_width = max(
            (self.fm.horizontalAdvance(line) for line in plain_text.split("\n")),
            default=0,
        )
        self.bubble_width = min(text_width + self.padding * 2, max_width)
        inner_width = self.bubble_width - self.padding * 2
        self.display_text = self._fit_tail(
            plain_text, inner_width, self.fm.lineSpacing() * self.MAX_LINES
        )
        text_height = self._text_height(self.display_text, inner_width)
        self.bubble_height = max(text_height, self.fm.height()) + self.padding * 2

        # 꼬리 공간 추가
        self.bubble_height += 15

        self.setFixedSize(self.bubble_width, self.bubble_height)

    def update_text(self, text: str) -> None:
        """말풍선 텍스트를 갱신하고 크기를 재계산합니다."""
        self.text = text
        self.calculate_size()
        self.update_position()
        self.update()

    def update_position(self):
        """말풍선 위치 업데이트"""
        if not self.parent_widget:
            return

        # 캐릭터의 화면 좌표
        parent_rect = self.parent_widget.rect()
        parent_pos = self.parent_widget.mapToGlobal(parent_rect.topLeft())

        # 가로 중앙 정렬
        x = parent_pos.x() + (parent_rect.width() - self.bubble_width) // 2

        head_top_offset = getattr(self.parent_widget, "head_top_offset", None)
        head_top_offset = int(head_top_offset() or 0) if callable(head_top_offset) else 0
        y = parent_pos.y() + head_top_offset - self.bubble_height - 5

        # 캐릭터가 있는 화면의 작업 영역 안으로 제한 (머리 위 배치는 유지)
        screen = self.parent_widget.screen()
        if screen is not None:
            area = screen.availableGeometry()
            x = max(area.left(), min(x, area.right() - self.bubble_width + 1))
            y = max(area.top() + 10, y)
        else:
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
        painter.drawText(
            text_rect, Qt.TextWordWrap | Qt.AlignCenter, getattr(self, "display_text", self.text)
        )
