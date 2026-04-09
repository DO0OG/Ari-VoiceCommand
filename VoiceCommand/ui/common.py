"""
UI 공용 유틸리티 (UI Common Utilities)
반복되는 위젯 생성·레이아웃 조작 패턴을 한 곳에 모은다.

주요 제공 요소:
  - clear_layout()       레이아웃 내 위젯 일괄 제거
  - apply_shadow()       QGraphicsDropShadowEffect 적용
  - create_input_field() 스타일 통일된 QLineEdit
  - create_icon_button() 아이콘 버튼 팩토리
  - show_temp_status()   타이머 기반 일시 상태 메시지
  - FloatingPanel        프레임리스 플로팅 창 기반 클래스
"""
from typing import Callable, Optional

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QApplication, QFrame, QGraphicsDropShadowEffect, QHBoxLayout,
    QLabel, QLayout, QLineEdit, QMainWindow, QPushButton, QVBoxLayout,
    QWidget,
)

from ui import theme as theme_module


# ── 레이아웃 유틸 ─────────────────────────────────────────────────────────────

def clear_layout(layout: QLayout) -> None:
    """레이아웃 내 모든 위젯을 안전하게 제거하고 메모리를 해제한다."""
    while layout.count():
        item = layout.takeAt(0)
        if item and item.widget():
            item.widget().deleteLater()


# ── 시각 효과 유틸 ────────────────────────────────────────────────────────────

def apply_shadow(
    widget: QWidget,
    blur_radius: int = theme_module.SHADOW_BLUR,
    offset_y: int = theme_module.SHADOW_OFFSET,
) -> None:
    """위젯에 드롭 섀도우 효과를 적용한다."""
    shadow = QGraphicsDropShadowEffect(widget)
    shadow.setBlurRadius(blur_radius)
    shadow.setColor(Qt.black)
    shadow.setOffset(0, offset_y)
    widget.setGraphicsEffect(shadow)


# ── 위젯 팩토리 ───────────────────────────────────────────────────────────────

def create_input_field(
    placeholder: str = "",
    font_size: int = theme_module.FONT_SIZE_NORMAL,
    height: int = 32,
) -> QLineEdit:
    """테마 스타일이 적용된 QLineEdit를 생성한다."""
    w = QLineEdit()
    w.setPlaceholderText(placeholder)
    w.setFont(QFont(theme_module.FONT_KO, font_size))
    w.setFixedHeight(height)
    w.setStyleSheet(theme_module.INPUT_STYLE)
    return w


def create_icon_button(
    icon: str,
    tooltip: str,
    size: int,
    color: str,
    callback: Optional[Callable] = None,
) -> QPushButton:
    """아이콘 버튼을 생성한다. callback이 주어지면 clicked에 연결한다."""
    btn = QPushButton(icon)
    btn.setFixedSize(size, size)
    btn.setToolTip(tooltip)
    btn.setCursor(Qt.PointingHandCursor)
    btn.setStyleSheet(theme_module.icon_btn_style(color, size))
    if callback:
        btn.clicked.connect(callback)
    return btn


def create_section_label(text: str, color: str = "") -> QLabel:
    """섹션 헤더 레이블을 생성한다."""
    lbl = QLabel(text)
    lbl.setFont(QFont(theme_module.FONT_KO, theme_module.FONT_SIZE_NORMAL, QFont.Bold))
    lbl.setStyleSheet(f"color: {color or theme_module.COLOR_PRIMARY};")
    return lbl


def create_muted_label(text: str) -> QLabel:
    """흐린 색 보조 텍스트 레이블을 생성한다."""
    lbl = QLabel(text)
    lbl.setFont(QFont(theme_module.FONT_KO, theme_module.FONT_SIZE_NORMAL))
    lbl.setStyleSheet(f"color: {theme_module.COLOR_MUTED};")
    return lbl


# ── 상태 메시지 ───────────────────────────────────────────────────────────────

def show_temp_status(
    label: QLabel,
    msg: str,
    duration_ms: int = theme_module.TEMP_STATUS_DURATION,
) -> None:
    """레이블에 메시지를 표시하고 duration_ms 후 자동으로 지운다."""
    label.setText(msg)
    QTimer.singleShot(duration_ms, lambda: label.setText(""))


# ── 공통 타이틀 바 ────────────────────────────────────────────────────────────

class PanelTitleBar(QFrame):
    """드래그 이동 + 닫기 버튼이 포함된 공통 타이틀 바.

    FloatingPanel 기반 클래스에서 자동으로 사용된다.
    추가 버튼이 필요하면 subclass에서 add_button()을 호출한다.
    """

    def __init__(self, title: str, parent: QMainWindow):
        super().__init__(parent)
        self._win = parent
        self._drag_pos = None
        self.setFixedHeight(theme_module.TITLEBAR_HEIGHT)
        self._lay = QHBoxLayout(self)
        self._lay.setContentsMargins(14, 0, 10, 0)

        self._title_lbl = QLabel(title)
        self._title_lbl.setFont(QFont(theme_module.FONT_KO, theme_module.FONT_SIZE_TITLE, QFont.Bold))
        self._lay.addWidget(self._title_lbl)
        self._lay.addStretch()

        # 닫기 버튼은 항상 맨 오른쪽
        self._close_btn = QPushButton("✕")
        self._close_btn.setFixedSize(30, 30)
        self._close_btn.setCursor(Qt.PointingHandCursor)
        self._close_btn.clicked.connect(parent.hide)
        self._lay.addWidget(self._close_btn)
        self.refresh_theme()

    def add_button(
        self,
        icon: str,
        tooltip: str,
        callback: Callable,
        size: int = theme_module.BUTTON_LG,
    ) -> QPushButton:
        """닫기 버튼 앞에 아이콘 버튼을 추가한다."""
        btn = QPushButton(icon)
        btn.setFixedSize(size, size)
        btn.setToolTip(tooltip)
        btn.setCursor(Qt.PointingHandCursor)
        btn.setStyleSheet("""
            QPushButton { background: rgba(255,255,255,15); color: white;
                           border: none; border-radius: 16px; font-size: 14px; }
            QPushButton:hover { background: rgba(255,255,255,35); }
        """)
        btn.clicked.connect(callback)
        # 닫기 버튼(index=-1) 직전에 삽입
        count = self._lay.count()
        self._lay.insertWidget(count - 1, btn)
        return btn

    def refresh_theme(self) -> None:
        self.setFixedHeight(theme_module.TITLEBAR_HEIGHT)
        self.setStyleSheet(f"""
            QFrame {{ background-color: {theme_module.COLOR_TITLEBAR};
                      border-top-left-radius: {theme_module.RADIUS_LG};
                      border-top-right-radius: {theme_module.RADIUS_LG}; }}
        """)
        self._title_lbl.setFont(QFont(theme_module.FONT_KO, theme_module.FONT_SIZE_TITLE, QFont.Bold))
        self._title_lbl.setStyleSheet("color: white;")
        self._close_btn.setStyleSheet(theme_module.close_btn_style())

    def set_title(self, text: str) -> None:
        self._title_lbl.setText(text)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_pos = event.globalPos() - self._win.pos()

    def mouseMoveEvent(self, event):
        if event.buttons() == Qt.LeftButton and self._drag_pos is not None:
            self._win.move(event.globalPos() - self._drag_pos)

    def mouseReleaseEvent(self, event):
        self._drag_pos = None


# ── 프레임리스 플로팅 패널 기반 클래스 ───────────────────────────────────────

class FloatingPanel(QMainWindow):
    """프레임리스·반투명 배경의 플로팅 패널 기반 클래스.

    상속해서 사용할 때:
      1. super().__init__(title, width, height, parent)
      2. self.content_layout 에 콘텐츠를 추가
      3. 타이틀 바 버튼이 필요하면 self.title_bar.add_button(...) 사용

    예시:
        class MyPanel(FloatingPanel):
            def __init__(self):
                super().__init__("🔧 내 패널", 400, 500)
                lbl = QLabel("내용")
                self.content_layout.addWidget(lbl)
    """

    def __init__(
        self,
        title: str,
        width: int,
        height: int,
        parent=None,
        close_hides: bool = True,
    ):
        super().__init__(parent)
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.resize(width, height)
        self._title_text = title
        self._build_shell(title)

    def _build_shell(self, title: str) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        outer = QVBoxLayout(central)
        outer.setContentsMargins(theme_module.MARGIN_PANEL, theme_module.MARGIN_PANEL, theme_module.MARGIN_PANEL, theme_module.MARGIN_PANEL)

        self._bg_frame = QFrame()
        self._bg_frame.setObjectName("FloatingPanelBg")
        apply_shadow(self._bg_frame, theme_module.SHADOW_BLUR_LG, theme_module.SHADOW_OFFSET_SM)
        outer.addWidget(self._bg_frame)

        self._bg_layout = QVBoxLayout(self._bg_frame)
        self._bg_layout.setContentsMargins(0, 0, 0, 0)
        self._bg_layout.setSpacing(0)

        self.title_bar = PanelTitleBar(title, self)
        self._bg_layout.addWidget(self.title_bar)

        # 서브 클래스가 위젯을 추가하는 레이아웃
        content_widget = QWidget()
        content_widget.setObjectName("FloatingPanelContent")
        content_widget.setStyleSheet(f"#FloatingPanelContent {{ background: {theme_module.COLOR_BG_PANEL}; }}")
        self.content_layout = QVBoxLayout(content_widget)
        self.content_layout.setContentsMargins(0, 0, 0, 0)
        self.content_layout.setSpacing(0)
        self._bg_layout.addWidget(content_widget)
        self.refresh_shell_theme()

    def show_near(self, x: int, y: int) -> None:
        """지정 좌표 근처에 화면 경계를 벗어나지 않도록 표시한다."""
        screen = QApplication.primaryScreen().geometry()
        fx = min(x + 10, screen.width() - self.width() - 10)
        fy = max(20, min(y, screen.height() - self.height() - 40))
        self.move(fx, fy)
        self.show()
        self.activateWindow()

    def refresh_shell_theme(self) -> None:
        central = self.centralWidget()
        if central and central.layout():
            central.layout().setContentsMargins(
                theme_module.MARGIN_PANEL,
                theme_module.MARGIN_PANEL,
                theme_module.MARGIN_PANEL,
                theme_module.MARGIN_PANEL,
            )
        self._bg_frame.setStyleSheet(f"""
            #FloatingPanelBg {{ background-color: {theme_module.COLOR_BG_PANEL};
                                border-radius: {theme_module.RADIUS_LG};
                                border: 1px solid {theme_module.COLOR_BORDER_LIGHT}; }}
        """)
        for idx in range(self._bg_layout.count()):
            item = self._bg_layout.itemAt(idx)
            widget = item.widget() if item else None
            if widget and widget.objectName() == "FloatingPanelContent":
                widget.setStyleSheet(f"#FloatingPanelContent {{ background: {theme_module.COLOR_BG_PANEL}; }}")
        apply_shadow(self._bg_frame, theme_module.SHADOW_BLUR_LG, theme_module.SHADOW_OFFSET_SM)
        self.title_bar.refresh_theme()
