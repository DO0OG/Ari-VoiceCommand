"""에이전트 스킬 관리 다이얼로그."""
from __future__ import annotations

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QProgressDialog,
    QPushButton,
    QVBoxLayout,
)

from i18n.translator import _
from ui.common import create_muted_label
from ui.theme import secondary_btn_style


class _SkillInstallThread(QThread):
    done = Signal(object)
    error = Signal(str)

    def __init__(self, source: str, skills_dir: str):
        super().__init__()
        self.source = source
        self.skills_dir = skills_dir

    def run(self) -> None:
        try:
            from agent.skill_installer import SkillInstaller

            installed = SkillInstaller(self.skills_dir).install(self.source)
            self.done.emit(installed)
        except Exception as exc:
            self.error.emit(str(exc))


class SkillsDialog(QDialog):
    """설치된 SKILL.md 스킬을 미리보기/설치/활성화/삭제한다."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._install_thread: _SkillInstallThread | None = None
        self.setWindowTitle(_("🧩 스킬 관리"))
        self.resize(860, 580)
        self._init_ui()
        self._refresh_list()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.addWidget(create_muted_label(_("스킬을 선택하면 SKILL.md 내용이 표시됩니다.")))

        source_row = QHBoxLayout()
        self.source_input = QLineEdit()
        self.source_input.setPlaceholderText(
            _("GitHub (예: NomaDamas/k-skill) 또는 URL 또는 로컬 경로")
        )
        source_row.addWidget(self.source_input, 1)
        install_button = QPushButton(_("설치"))
        install_button.setStyleSheet(secondary_btn_style())
        install_button.clicked.connect(self._on_install)
        source_row.addWidget(install_button)
        layout.addLayout(source_row)

        content_row = QHBoxLayout()
        self.skill_list = QListWidget()
        self.skill_list.currentItemChanged.connect(self._on_select)
        content_row.addWidget(self.skill_list, 1)

        preview_column = QVBoxLayout()
        self.summary_label = QLabel("")
        self.summary_label.setWordWrap(True)
        preview_column.addWidget(self.summary_label)
        self.mcp_label = create_muted_label("")
        self.mcp_label.setVisible(False)
        preview_column.addWidget(self.mcp_label)
        self.preview = QPlainTextEdit()
        self.preview.setReadOnly(True)
        preview_column.addWidget(self.preview, 1)
        content_row.addLayout(preview_column, 2)
        layout.addLayout(content_row, 1)

        button_row = QHBoxLayout()
        self.toggle_button = QPushButton(_("비활성화"))
        self.toggle_button.setStyleSheet(secondary_btn_style())
        self.toggle_button.clicked.connect(self._on_toggle)
        update_button = QPushButton(_("업데이트"))
        update_button.setStyleSheet(secondary_btn_style())
        update_button.clicked.connect(self._on_update)
        delete_button = QPushButton(_("삭제"))
        delete_button.setStyleSheet(secondary_btn_style())
        delete_button.clicked.connect(self._on_delete)
        close_button = QPushButton(_("닫기"))
        close_button.clicked.connect(self.accept)
        button_row.addWidget(self.toggle_button)
        button_row.addWidget(update_button)
        button_row.addWidget(delete_button)
        button_row.addStretch(1)
        button_row.addWidget(close_button)
        layout.addLayout(button_row)

    def _refresh_list(self) -> None:
        from agent.skill_manager import get_skill_manager

        self.skill_list.clear()
        for skill in get_skill_manager().load_all():
            prefix = "✓" if skill.enabled else "○"
            suffix = " [MCP]" if skill.is_mcp_skill else ""
            item = QListWidgetItem(f"{prefix} {skill.name}{suffix}")
            item.setData(Qt.UserRole, skill.name)
            self.skill_list.addItem(item)
        if self.skill_list.count():
            self.skill_list.setCurrentRow(0)

    def _selected_skill_name(self) -> str:
        item = self.skill_list.currentItem()
        return str(item.data(Qt.UserRole) or "") if item else ""

    def _on_select(self, item, _previous) -> None:
        del _previous
        from agent.skill_manager import get_skill_manager

        if item is None:
            self.summary_label.clear()
            self.preview.clear()
            self.mcp_label.setVisible(False)
            return
        skill = get_skill_manager().get_skill(str(item.data(Qt.UserRole) or ""))
        if skill is None:
            return
        self.summary_label.setText(skill.description)
        self.preview.setPlainText(skill.content)
        self.toggle_button.setText(_("활성화") if not skill.enabled else _("비활성화"))
        if skill.is_mcp_skill:
            self.mcp_label.setText(f"🔌 MCP: {skill.mcp_endpoint}")
            self.mcp_label.setVisible(True)
        else:
            self.mcp_label.setVisible(False)

    def _on_install(self) -> None:
        source = self.source_input.text().strip()
        if not source:
            return
        if self._install_thread and self._install_thread.isRunning():
            return

        from agent.skill_manager import get_skill_manager

        progress = QProgressDialog(_("설치 중"), None, 0, 0, self)
        progress.setLabelText(_("스킬 설치 중..."))
        progress.setWindowModality(Qt.WindowModal)
        progress.show()

        self._install_thread = _SkillInstallThread(source, get_skill_manager().skills_dir)
        self._install_thread.done.connect(lambda names: self._on_install_done(names, progress))
        self._install_thread.error.connect(lambda message: self._on_install_error(message, progress))
        self._install_thread.start()

    def _on_install_done(self, names: object, progress: QProgressDialog) -> None:
        progress.close()
        installed_names = list(names) if isinstance(names, (list, tuple)) else []
        if installed_names:
            QMessageBox.information(
                self,
                _("설치 완료"),
                _("설치된 스킬: {names}").format(names=", ".join(installed_names)),
            )
            self._refresh_list()
        else:
            QMessageBox.warning(self, _("설치 실패"), _("스킬을 설치할 수 없었습니다."))

    def _on_install_error(self, message: str, progress: QProgressDialog) -> None:
        progress.close()
        QMessageBox.warning(self, _("설치 실패"), message)

    def _on_toggle(self) -> None:
        from agent.skill_manager import get_skill_manager

        name = self._selected_skill_name()
        skill = get_skill_manager().get_skill(name)
        if skill is None:
            return
        if skill.enabled:
            get_skill_manager().disable(name)
        else:
            get_skill_manager().enable(name)
        self._refresh_list()

    def _on_update(self) -> None:
        from agent.skill_installer import SkillInstaller
        from agent.skill_manager import get_skill_manager

        name = self._selected_skill_name()
        if not name:
            return
        ok = SkillInstaller(get_skill_manager().skills_dir).update(name)
        if ok:
            get_skill_manager().load_all()
            self._refresh_list()
            QMessageBox.information(self, _("업데이트"), _("{name} 업데이트 완료").format(name=name))
        else:
            QMessageBox.warning(self, _("업데이트 실패"), _("설치 원본 정보가 없습니다."))

    def _on_delete(self) -> None:
        from agent.skill_manager import get_skill_manager

        name = self._selected_skill_name()
        if not name:
            return
        confirmed = QMessageBox.question(
            self,
            _("스킬 삭제"),
            _("{name} 스킬을 삭제할까요?").format(name=name),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if confirmed != QMessageBox.Yes:
            return
        get_skill_manager().remove(name)
        self._refresh_list()
