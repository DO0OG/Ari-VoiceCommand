"""
테마 팔레트 편집 위젯.
"""

from __future__ import annotations

import json
from datetime import datetime

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QColorDialog, QDialog, QGroupBox, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton, QScrollArea, QTextEdit, QVBoxLayout, QWidget

from ui import theme

COLOR_GROUPS = {
    "주요 색상": ["primary", "primary_dark", "accent", "success", "warning", "danger", "muted"],
    "텍스트": ["text_primary", "text_secondary", "text_panel"],
    "배경": ["bg_main", "bg_panel", "bg_white", "bg_input", "bg_chat_user", "bg_chat_aari"],
    "테두리": ["border_light", "border_div", "border_input", "border_card"],
    "기타": ["titlebar", "bg_suggestion", "bg_chip_primary", "bg_chip_warn"],
}
HEX_ONLY_KEYS = {"bg_main", "bg_panel", "bg_suggestion", "bg_status", "bg_dashboard"}


class ColorSwatch(QWidget):
    color_changed = Signal(str, str)

    def __init__(self, color_key: str, initial_value: str, parent=None):
        super().__init__(parent)
        self.color_key = color_key
        self._swatch = QLabel()
        self._label = QLabel(color_key)
        self.value_input = QLineEdit(initial_value)
        self._pick_btn = QPushButton("선택")
        self._build_ui()
        self.set_value(initial_value)

    def _build_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self._swatch.setFixedSize(20, 20)
        self._label.setMinimumWidth(180)
        self.value_input.textChanged.connect(self._on_value_changed)
        self._pick_btn.clicked.connect(self._on_pick)
        if self.color_key in HEX_ONLY_KEYS:
            self._pick_btn.setEnabled(False)
        layout.addWidget(self._swatch)
        layout.addWidget(self._label)
        layout.addWidget(self.value_input, 1)
        layout.addWidget(self._pick_btn)

    def _update_swatch(self, hex_value: str):
        self._swatch.setStyleSheet(f"background:{hex_value}; border:1px solid #999; border-radius:4px;")

    def _on_pick(self):
        color = QColorDialog.getColor(parent=self)
        if color.isValid():
            self.value_input.setText(color.name())

    def _on_value_changed(self, text: str):
        if text.strip():
            self._update_swatch(text.strip())
            self.color_changed.emit(self.color_key, text.strip())

    def set_value(self, value: str):
        self.value_input.blockSignals(True)
        self.value_input.setText(value)
        self.value_input.blockSignals(False)
        self._update_swatch(value)

    def get_value(self) -> str:
        return self.value_input.text().strip()


class ThemeEditorWidget(QWidget):
    theme_saved = Signal(str)
    palette_changed = Signal()

    def __init__(self, initial_colors: dict[str, str], parent=None):
        super().__init__(parent)
        self._colors = dict(initial_colors or {})
        self._preset_colors = dict(initial_colors or {})
        self._swatches: dict[str, ColorSwatch] = {}
        self.name_input = QLineEdit()
        self.json_edit = QTextEdit()
        self._build_ui()
        self._load_colors(self._colors)

    def _build_ui(self):
        root = QVBoxLayout(self)
        palette_group = QGroupBox("팔레트 편집")
        palette_layout = QVBoxLayout(palette_group)
        top = QHBoxLayout()
        self.name_input.setPlaceholderText("테마 이름")
        save_btn = QPushButton("테마로 저장")
        reset_btn = QPushButton("프리셋 초기화")
        save_btn.clicked.connect(self._on_save)
        reset_btn.clicked.connect(self._on_reset)
        top.addWidget(self.name_input, 1)
        top.addWidget(save_btn)
        top.addWidget(reset_btn)
        palette_layout.addLayout(top)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setMaximumHeight(400)
        scroll_body = QWidget()
        scroll_layout = QVBoxLayout(scroll_body)
        for group_name, keys in COLOR_GROUPS.items():
            box = QGroupBox(group_name)
            grid = QGridLayout(box)
            for row, key in enumerate(keys):
                swatch = ColorSwatch(key, self._colors.get(key, ""))
                swatch.color_changed.connect(self._on_swatch_changed)
                self._swatches[key] = swatch
                grid.addWidget(swatch, row, 0)
            scroll_layout.addWidget(box)
        scroll_layout.addStretch()
        scroll.setWidget(scroll_body)
        palette_layout.addWidget(scroll)
        root.addWidget(palette_group)
        json_group = QGroupBox("JSON 직접 편집")
        json_layout = QVBoxLayout(json_group)
        self.json_edit.setFont(QFont("Consolas", 9))
        json_layout.addWidget(self.json_edit)
        buttons = QHBoxLayout()
        parse_btn = QPushButton("JSON 적용")
        copy_btn = QPushButton("복사")
        parse_btn.clicked.connect(self._on_parse_json)
        copy_btn.clicked.connect(lambda: self.json_edit.selectAll() or self.json_edit.copy())
        buttons.addWidget(parse_btn)
        buttons.addWidget(copy_btn)
        json_layout.addLayout(buttons)
        root.addWidget(json_group)

    def _load_colors(self, colors: dict[str, str]):
        self._colors = dict(colors or {})
        for key, swatch in self._swatches.items():
            swatch.set_value(self._colors.get(key, ""))
        self._sync_json_edit()

    def _on_swatch_changed(self, key: str, value: str):
        self._colors[key] = value
        self._sync_json_edit()
        self.palette_changed.emit()

    def _sync_json_edit(self):
        self.json_edit.blockSignals(True)
        self.json_edit.setPlainText(json.dumps(self._colors, ensure_ascii=False, indent=2))
        self.json_edit.blockSignals(False)

    def _on_parse_json(self):
        try:
            parsed = json.loads(self.json_edit.toPlainText() or "{}")
            if not isinstance(parsed, dict):
                raise ValueError("dict 형식 필요")
        except Exception:
            QMessageBox.warning(self, "JSON 형식 오류", "JSON 형식 오류")
            return
        self._load_colors({str(key): str(value) for key, value in parsed.items()})
        self.palette_changed.emit()

    def _on_save(self):
        theme_key = "custom_" + datetime.now().strftime("%Y%m%d_%H%M%S")
        name = self.name_input.text().strip() or theme_key
        try:
            theme.save_custom_theme(theme_key, name, self._colors, "")
        except Exception as exc:
            QMessageBox.warning(self, "테마 저장 실패", str(exc))
            return
        QMessageBox.information(self, "테마 저장 완료", f"'{name}' 저장됨")
        self.theme_saved.emit(theme_key)

    def _on_reset(self):
        self._load_colors(self._preset_colors)
        self.palette_changed.emit()

    def get_current_colors(self) -> dict[str, str]:
        return dict(self._colors)

    def load_preset(self, colors: dict[str, str]):
        self._preset_colors = dict(colors or {})
        self._load_colors(self._preset_colors)


class ThemeEditorDialog(QDialog):
    """ThemeEditorWidget을 별도 창으로 감싸는 다이얼로그."""

    palette_changed = Signal()
    theme_saved = Signal(str)

    def __init__(self, initial_colors: dict[str, str], parent=None):
        super().__init__(parent)
        self.setWindowTitle("팔레트 편집")
        self.setWindowFlags(Qt.Window)
        self.setMinimumSize(620, 720)
        self.setAttribute(Qt.WA_DeleteOnClose, False)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 4)

        self.editor = ThemeEditorWidget(initial_colors, self)
        self.editor.palette_changed.connect(self.palette_changed)
        self.editor.theme_saved.connect(self.theme_saved)
        layout.addWidget(self.editor)

        close_btn = QPushButton("닫기")
        close_btn.clicked.connect(self.close)
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)

    def load_preset(self, colors: dict[str, str]):
        self.editor.load_preset(colors)

    def get_current_colors(self) -> dict[str, str]:
        return self.editor.get_current_colors()


if __name__ == "__main__":
    import logging

    logging.basicConfig(level=logging.DEBUG)
    logging.debug("ThemeEditorWidget module")
