"""
메모리 시각화 & 편집 패널 (Memory Panel)
아리가 기억하는 사용자 정보를 실시간으로 보여주고 직접 편집·삭제할 수 있습니다.
FloatingPanel 기반 클래스를 사용해 구조를 공유합니다.

탭 구성:
  기본 정보  — 이름·위치·관심사·메모 편집
  사실       — 저장된 Facts 목록 (신뢰도·만료일·삭제)
  통계       — 명령 빈도·선호도·대화 주제 시각화
"""
import logging

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QFrame, QGridLayout, QHBoxLayout, QLabel,
    QPushButton, QScrollArea, QTabWidget, QVBoxLayout, QWidget,
)

from ui.common import (
    FloatingPanel, clear_layout, create_input_field,
    create_section_label, create_muted_label, show_temp_status,
)
from ui.theme import (
    FONT_KO, FONT_SIZE_NORMAL, FONT_SIZE_SMALL,
    COLOR_PRIMARY, COLOR_DANGER, COLOR_MUTED,
    COLOR_BG_WHITE, COLOR_BG_CHIP_PRIMARY, COLOR_BG_CHIP_WARN,
    SCROLLBAR_THIN_STYLE, TAB_STYLE, primary_btn_style,
    WINDOW_W_MEMORY, WINDOW_H_MEMORY,
)

logger = logging.getLogger(__name__)


# ── 사실(Fact) 행 ─────────────────────────────────────────────────────────────

class FactRow(QFrame):
    """Facts 탭에서 하나의 fact 항목을 표시하는 행."""

    delete_requested = Signal(str)  # key

    def __init__(self, key: str, entry: dict, parent=None):
        super().__init__(parent)
        self._key = key
        self.setStyleSheet(f"QFrame {{ background: {COLOR_BG_WHITE}; border-radius: 8px; border: 1px solid #eee; }}")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 7, 10, 7)

        value = entry.get("value", "")
        conf  = int(entry.get("confidence", 0) * 100)
        exp   = entry.get("expires_at", "")[:10] if entry.get("expires_at") else "∞"

        key_lbl = QLabel(f"<b>{key}</b>")
        key_lbl.setFont(QFont(FONT_KO, FONT_SIZE_SMALL))
        key_lbl.setMinimumWidth(110)
        lay.addWidget(key_lbl)

        val_lbl = QLabel(str(value)[:50])
        val_lbl.setFont(QFont(FONT_KO, FONT_SIZE_SMALL))
        val_lbl.setStyleSheet("color: #333;")
        lay.addWidget(val_lbl, 1)

        meta_lbl = QLabel(f"{conf}%  exp:{exp}")
        meta_lbl.setFont(QFont(FONT_KO, FONT_SIZE_SMALL - 1))
        meta_lbl.setStyleSheet(f"color: {COLOR_MUTED};")
        lay.addWidget(meta_lbl)

        del_btn = QPushButton("✕")
        del_btn.setFixedSize(22, 22)
        del_btn.setStyleSheet(
            f"QPushButton {{ background: {COLOR_DANGER}; color: white; "
            f"border: none; border-radius: 11px; font-size: 10px; }}"
        )
        del_btn.clicked.connect(lambda: self.delete_requested.emit(self._key))
        lay.addWidget(del_btn)


# ── 탭: 기본 정보 ─────────────────────────────────────────────────────────────

class _BioTab(QWidget):
    def __init__(self, ctx_manager, parent=None):
        super().__init__(parent)
        self._ctx = ctx_manager
        self._build()

    def _build(self) -> None:
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.setSpacing(10)

        bio = self._ctx.context.get("user_bio", {}) if self._ctx else {}
        self._fields: dict = {}

        for label, field_key, placeholder in [
            ("이름", "name", "사용자 이름"),
            ("위치", "location", "도시 또는 지역"),
        ]:
            row = QHBoxLayout()
            lbl = QLabel(label)
            lbl.setFont(QFont(FONT_KO, FONT_SIZE_NORMAL, QFont.Bold))
            lbl.setFixedWidth(50)
            inp = create_input_field(placeholder)
            inp.setText(str(bio.get(field_key, "")))
            row.addWidget(lbl)
            row.addWidget(inp)
            lay.addLayout(row)
            self._fields[field_key] = inp

        lay.addWidget(create_section_label("관심사 (쉼표로 구분)"))
        self._interests = create_input_field("예: 음악, 영화, 독서")
        self._interests.setText(", ".join(bio.get("interests", [])))
        lay.addWidget(self._interests)

        lay.addWidget(create_section_label("메모 (쉼표로 구분)"))
        self._memos = create_input_field("예: 고양이 좋아함, 야행성")
        self._memos.setText(", ".join(bio.get("memos", [])))
        lay.addWidget(self._memos)

        save_btn = QPushButton("저장")
        save_btn.setFixedHeight(34)
        save_btn.setFont(QFont(FONT_KO, FONT_SIZE_NORMAL, QFont.Bold))
        save_btn.setCursor(Qt.PointingHandCursor)
        save_btn.setStyleSheet(primary_btn_style())
        save_btn.clicked.connect(self._save)
        lay.addWidget(save_btn)

        self._status = QLabel("")
        self._status.setFont(QFont(FONT_KO, FONT_SIZE_SMALL))
        self._status.setStyleSheet(f"color: {COLOR_MUTED};")
        lay.addWidget(self._status)
        lay.addStretch()

    def _save(self) -> None:
        if not self._ctx:
            return
        try:
            for key, inp in self._fields.items():
                self._ctx.update_bio(key, inp.text().strip())
            interests = [s.strip() for s in self._interests.text().split(",") if s.strip()]
            memos     = [s.strip() for s in self._memos.text().split(",") if s.strip()]
            self._ctx.context["user_bio"]["interests"] = interests
            self._ctx.context["user_bio"]["memos"]     = memos
            self._ctx.save_context()
            show_temp_status(self._status, "✅ 저장 완료")
        except Exception as e:
            show_temp_status(self._status, f"⚠️ 저장 실패: {e}")


# ── 탭: 사실 (Facts) ─────────────────────────────────────────────────────────

class _FactsTab(QWidget):
    def __init__(self, ctx_manager, parent=None):
        super().__init__(parent)
        self._ctx = ctx_manager
        self._build()

    def _build(self) -> None:
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet(SCROLLBAR_THIN_STYLE)

        self._container = QWidget()
        self._inner = QVBoxLayout(self._container)
        self._inner.setAlignment(Qt.AlignTop)
        self._inner.setSpacing(6)
        self._inner.setContentsMargins(12, 10, 12, 10)
        scroll.setWidget(self._container)
        lay.addWidget(scroll)

        self._populate()

    def _populate(self) -> None:
        clear_layout(self._inner)
        facts = self._ctx.context.get("facts", {}) if self._ctx else {}
        if not facts:
            self._inner.addWidget(create_muted_label("아직 저장된 사실이 없습니다."))
            return
        sorted_facts = sorted(
            facts.items(),
            key=lambda kv: (kv[1].get("updated_at", ""), kv[1].get("confidence", 0)),
            reverse=True,
        )
        for key, entry in sorted_facts:
            row = FactRow(key, entry)
            row.delete_requested.connect(self._delete_fact)
            self._inner.addWidget(row)

    def _delete_fact(self, key: str) -> None:
        if self._ctx and key in self._ctx.context.get("facts", {}):
            del self._ctx.context["facts"][key]
            self._ctx.save_context()
            self._populate()

    def refresh(self) -> None:
        self._populate()


# ── 탭: 통계 ──────────────────────────────────────────────────────────────────

class _StatsTab(QWidget):
    def __init__(self, ctx_manager, parent=None):
        super().__init__(parent)
        self._ctx = ctx_manager
        self._build()

    def _build(self) -> None:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; }")

        container = QWidget()
        lay = QVBoxLayout(container)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(14)
        scroll.setWidget(container)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)

        ctx = self._ctx.context if self._ctx else {}

        # 자주 쓰는 명령어
        lay.addWidget(create_section_label("자주 쓰는 명령어"))
        cmd_freq = sorted(ctx.get("command_frequency", {}).items(), key=lambda x: x[1], reverse=True)[:8]
        if cmd_freq:
            grid = QGridLayout()
            grid.setSpacing(6)
            for i, (cmd, cnt) in enumerate(cmd_freq):
                chip = QLabel(f"{cmd}  ×{cnt}")
                chip.setFont(QFont(FONT_KO, FONT_SIZE_NORMAL))
                chip.setAlignment(Qt.AlignCenter)
                chip.setStyleSheet(
                    f"QLabel {{ background: {COLOR_BG_CHIP_PRIMARY}; color: {COLOR_PRIMARY}; "
                    f"border-radius: 12px; padding: 4px 10px; }}"
                )
                grid.addWidget(chip, i // 3, i % 3)
            lay.addLayout(grid)
        else:
            lay.addWidget(create_muted_label("기록 없음"))

        # 대화 주제
        lay.addWidget(create_section_label("대화 주제"))
        topics = sorted(ctx.get("conversation_topics", {}).items(), key=lambda x: x[1], reverse=True)[:10]
        if topics:
            topic_grid = QGridLayout()
            topic_grid.setHorizontalSpacing(6)
            topic_grid.setVerticalSpacing(6)
            for i, (topic, cnt) in enumerate(topics):
                chip = QLabel(f"#{topic}  {cnt}")
                chip.setFont(QFont(FONT_KO, FONT_SIZE_NORMAL))
                chip.setStyleSheet(
                    f"QLabel {{ background: {COLOR_BG_CHIP_WARN}; color: #e67e22; "
                    f"border-radius: 12px; padding: 4px 10px; }}"
                )
                chip.setWordWrap(True)
                chip.setMinimumWidth(0)
                topic_grid.addWidget(chip, i // 2, i % 2)
            lay.addLayout(topic_grid)
        else:
            lay.addWidget(create_muted_label("기록 없음"))

        # 선호도
        lay.addWidget(create_section_label("선호도"))
        prefs = ctx.get("preferences", {})
        if prefs:
            for cat, vals in list(prefs.items())[:6]:
                if not vals:
                    continue
                top_val, top_cnt = max(vals.items(), key=lambda x: x[1])
                row_lbl = QLabel(f"<b>{cat}</b>: {top_val}  ×{top_cnt}")
                row_lbl.setFont(QFont(FONT_KO, FONT_SIZE_NORMAL))
                row_lbl.setStyleSheet("color: #444;")
                lay.addWidget(row_lbl)
        else:
            lay.addWidget(create_muted_label("기록 없음"))

        lay.addStretch()


# ── 메인 패널 ─────────────────────────────────────────────────────────────────

class MemoryPanel(FloatingPanel):
    """아리 메모리 시각화 & 편집 패널."""

    def __init__(self, ctx_manager=None, parent=None):
        super().__init__("🧠  아리의 기억", WINDOW_W_MEMORY, WINDOW_H_MEMORY, parent)
        self._ctx = ctx_manager
        self._build_content()

    def _build_content(self) -> None:
        tabs = QTabWidget()
        tabs.setStyleSheet(TAB_STYLE)
        self._tabs = tabs

        self._bio_tab   = _BioTab(self._ctx)
        self._facts_tab = _FactsTab(self._ctx)
        self._stats_tab = _StatsTab(self._ctx)

        tabs.addTab(self._bio_tab,   "기본 정보")
        tabs.addTab(self._facts_tab, "사실 (Facts)")
        tabs.addTab(self._stats_tab, "통계")

        self.content_layout.addWidget(tabs)

    def refresh(self) -> None:
        """외부에서 데이터 갱신 요청 시 호출."""
        self._facts_tab.refresh()

    def show_near(self, x: int, y: int) -> None:
        super().show_near(x, y)
        self.refresh()

    def refresh_theme(self) -> None:
        current_index = self._tabs.currentIndex() if hasattr(self, "_tabs") else 0
        self.refresh_shell_theme()
        clear_layout(self.content_layout)
        self._build_content()
        self._tabs.setCurrentIndex(current_index)
        self.refresh()
