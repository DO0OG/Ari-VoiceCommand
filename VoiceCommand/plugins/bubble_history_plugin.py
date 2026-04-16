"""말풍선 히스토리 및 커스텀 메시지 플러그인."""
from __future__ import annotations

import json
import logging
import os


PLUGIN_INFO = {
    "name": "bubble_history_plugin",
    "version": "1.0.0",
    "api_version": "1.0",
    "description": "말풍선 히스토리 조회와 커스텀 메시지 관리 UI를 제공한다",
}

_widget_ref = None


def _show_history():
    from PySide6.QtWidgets import QDialog, QLabel, QListWidget, QVBoxLayout
    from core.resource_manager import ResourceManager
    from i18n.translator import _

    path = ResourceManager.get_writable_path("bubble_history.json")
    if not os.path.exists(path):
        if _widget_ref:
            _widget_ref.say(_("아직 히스토리가 없어요!"), duration=2000)
        return

    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except Exception as exc:
        logging.debug("[BubbleHistoryPlugin] 히스토리 로드 실패: %s", exc)
        if _widget_ref:
            _widget_ref.say(_("아직 히스토리가 없어요!"), duration=2000)
        return

    dialog = QDialog()
    dialog.setWindowTitle(_("말풍선 히스토리"))
    dialog.resize(400, 500)
    layout = QVBoxLayout(dialog)
    layout.addWidget(QLabel(_("최근 말풍선 기록 (최대 50개)")))
    history_list = QListWidget()
    for item in data.get("history", []):
        history_list.addItem(f"[{item['timestamp']}] {item['text']}")
    layout.addWidget(history_list)
    dialog.exec()


def _open_custom_msg_dialog():
    from PySide6.QtWidgets import (
        QDialog,
        QHBoxLayout,
        QLabel,
        QLineEdit,
        QListWidget,
        QPushButton,
        QVBoxLayout,
    )
    from core.resource_manager import ResourceManager
    from i18n.translator import _

    path = ResourceManager.get_writable_path("custom_messages.json")
    data = {"messages": []}
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
        except Exception as exc:
            logging.debug("[BubbleHistoryPlugin] 커스텀 메시지 로드 실패: %s", exc)

    dialog = QDialog()
    dialog.setWindowTitle(_("커스텀 메시지 관리"))
    dialog.resize(420, 400)
    layout = QVBoxLayout(dialog)
    layout.addWidget(QLabel(_("등록된 메시지 목록")))

    message_list = QListWidget()
    for message in data.get("messages", []):
        message_list.addItem(message)
    layout.addWidget(message_list)

    row = QHBoxLayout()
    edit = QLineEdit()
    edit.setPlaceholderText(_("새 메시지 입력..."))
    row.addWidget(edit)

    add_btn = QPushButton(_("추가"))

    def _add():
        text = edit.text().strip()
        if text:
            message_list.addItem(text)
            edit.clear()

    add_btn.clicked.connect(_add)
    row.addWidget(add_btn)

    delete_btn = QPushButton(_("삭제"))

    def _delete():
        for item in message_list.selectedItems():
            message_list.takeItem(message_list.row(item))

    delete_btn.clicked.connect(_delete)
    row.addWidget(delete_btn)
    layout.addLayout(row)

    save_btn = QPushButton(_("저장"))

    def _save():
        messages = [message_list.item(index).text() for index in range(message_list.count())]
        with open(path, "w", encoding="utf-8") as handle:
            json.dump({"messages": messages}, handle, ensure_ascii=False, indent=2)
        dialog.accept()

    save_btn.clicked.connect(_save)
    layout.addWidget(save_btn)
    dialog.exec()


def register(context):
    from i18n.translator import _

    global _widget_ref

    _widget_ref = getattr(context, "character_widget", None)
    if callable(getattr(context, "register_menu_action", None)):
        context.register_menu_action(_("📜 최근 말풍선 히스토리"), _show_history)
        context.register_menu_action(_("✏️ 커스텀 메시지 관리"), _open_custom_msg_dialog)

    logging.info("[BubbleHistoryPlugin] 로드 완료")
    return {"message": "bubble_history_plugin loaded", "has_widget": _widget_ref is not None}
