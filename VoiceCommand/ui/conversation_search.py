"""대화 기록 검색 UI."""
from __future__ import annotations

from datetime import datetime, timedelta

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDateEdit,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QPushButton,
    QPlainTextEdit,
    QVBoxLayout,
)


class ConversationSearchDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("대화 검색")
        self.resize(720, 520)
        self.search_input = QLineEdit(self)
        self.search_input.setPlaceholderText("검색어")
        self.start_date = QDateEdit(self)
        self.start_date.setCalendarPopup(True)
        self.end_date = QDateEdit(self)
        self.end_date.setCalendarPopup(True)
        now = datetime.now()
        self.start_date.setDate((now - timedelta(days=30)).date())
        self.end_date.setDate(now.date())
        self.result_list = QListWidget(self)
        self.preview = QPlainTextEdit(self)
        self.preview.setReadOnly(True)
        search_button = QPushButton("검색", self)
        search_button.clicked.connect(self.search)
        filters = QHBoxLayout()
        filters.addWidget(QLabel("시작"))
        filters.addWidget(self.start_date)
        filters.addWidget(QLabel("끝"))
        filters.addWidget(self.end_date)
        filters.addWidget(search_button)
        layout = QVBoxLayout(self)
        layout.addWidget(self.search_input)
        layout.addLayout(filters)
        layout.addWidget(self.result_list, 2)
        layout.addWidget(self.preview, 1)
        self.result_list.itemClicked.connect(lambda item: self.preview.setPlainText(item.data(Qt.UserRole) or item.text()))
        self.search_input.returnPressed.connect(self.search)

    def search(self) -> None:
        query = self.search_input.text().strip()
        self.result_list.clear()
        try:
            from memory.memory_index import get_memory_index
            index = get_memory_index()
            if query:
                results = index.search(query, limit=50)
            else:
                start = self.start_date.date().toPython()
                end = self.end_date.date().toPython()
                results = index.search_by_date(datetime.combine(start, datetime.min.time()), datetime.combine(end, datetime.max.time()))
            for result in results:
                item_text = f"[{result.timestamp}] {result.entry_type}: {result.content[:120]}"
                self.result_list.addItem(item_text)
                item = self.result_list.item(self.result_list.count() - 1)
                item.setData(Qt.UserRole, result.content)
        except Exception as exc:
            self.result_list.addItem(f"검색 실패: {exc}")
