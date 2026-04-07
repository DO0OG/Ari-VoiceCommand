"""
플러그인 관리 설정 페이지 위젯 (확장 탭)
"""
import os

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QLineEdit, QPushButton, QGroupBox, QListWidget, QListWidgetItem,
    QMessageBox,
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QDesktopServices
from PySide6.QtCore import QUrl

from ui.theme import secondary_btn_style
from ui.common import create_muted_label
from ui.marketplace_browser import MarketplaceFetchThread, MarketplaceInstallThread


class _PluginSettingsPage(QWidget):
    """플러그인 관리 및 마켓플레이스 탭 위젯."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._market_fetch_thread: MarketplaceFetchThread | None = None
        self._market_install_thread: MarketplaceInstallThread | None = None
        self._market_items: list[dict] = []
        self._init_ui()

    # ── UI 구성 ───────────────────────────────────────────────────────────────

    def _init_ui(self):
        vbox = QVBoxLayout(self)

        # 마켓플레이스 그룹
        marketplace_group = QGroupBox("마켓플레이스")
        mvbox = QVBoxLayout(marketplace_group)
        mvbox.addWidget(create_muted_label(
            "설정창 안에서 플러그인을 검색하고 바로 설치할 수 있습니다."
        ))

        search_row = QHBoxLayout()
        self.market_search_input = QLineEdit()
        self.market_search_input.setPlaceholderText("플러그인 검색")
        search_row.addWidget(self.market_search_input)
        market_search_btn = QPushButton("검색")
        market_search_btn.setStyleSheet(secondary_btn_style())
        market_search_btn.clicked.connect(self._refresh_marketplace_list)
        search_row.addWidget(market_search_btn)
        mvbox.addLayout(search_row)

        self.marketplace_list = QListWidget()
        mvbox.addWidget(self.marketplace_list)

        self.marketplace_status_label = create_muted_label("")
        mvbox.addWidget(self.marketplace_status_label)

        market_btn_row = QHBoxLayout()
        self.market_install_btn = QPushButton("선택 플러그인 설치")
        self.market_install_btn.setStyleSheet(secondary_btn_style())
        self.market_install_btn.clicked.connect(self._install_selected_marketplace_plugin)
        market_refresh_btn = QPushButton("목록 새로고침")
        market_refresh_btn.setStyleSheet(secondary_btn_style())
        market_refresh_btn.clicked.connect(self._refresh_marketplace_list)
        market_open_btn = QPushButton("웹 마켓플레이스 열기")
        market_open_btn.setStyleSheet(secondary_btn_style())
        market_open_btn.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl("https://ari-voice-command.vercel.app/marketplace"))
        )
        market_btn_row.addWidget(self.market_install_btn)
        market_btn_row.addWidget(market_refresh_btn)
        market_btn_row.addWidget(market_open_btn)
        mvbox.addLayout(market_btn_row)

        vbox.addWidget(marketplace_group)

        # 사용자 플러그인 그룹
        plugin_group = QGroupBox("사용자 플러그인")
        pvbox = QVBoxLayout(plugin_group)

        try:
            from core.resource_manager import ResourceManager
            plugin_dir = ResourceManager.ensure_plugin_files()
        except Exception:
            plugin_dir = os.path.join(os.getcwd(), "plugins")

        pvbox.addWidget(QLabel("플러그인 폴더:"))
        self.plugin_dir_input = QLineEdit(plugin_dir)
        self.plugin_dir_input.setReadOnly(True)
        pvbox.addWidget(self.plugin_dir_input)

        self.plugin_list = QListWidget()
        pvbox.addWidget(self.plugin_list)

        btn_row = QHBoxLayout()
        open_btn = QPushButton("플러그인 폴더 열기")
        open_btn.setStyleSheet(secondary_btn_style())
        open_btn.clicked.connect(self._open_plugin_folder)
        reload_btn = QPushButton("플러그인 목록 새로고침")
        reload_btn.setStyleSheet(secondary_btn_style())
        reload_btn.clicked.connect(self._refresh_plugin_list)
        btn_row.addWidget(open_btn)
        btn_row.addWidget(reload_btn)
        pvbox.addLayout(btn_row)

        vbox.addWidget(plugin_group)
        vbox.addStretch()

        self._refresh_plugin_list()
        self._refresh_marketplace_list()

    # ── 플러그인 목록 ──────────────────────────────────────────────────────────

    def _refresh_plugin_list(self):
        self.plugin_list.clear()
        try:
            from core.plugin_loader import get_plugin_manager
            plugins = get_plugin_manager().discover_plugins()
        except Exception as exc:
            item = QListWidgetItem(f"플러그인 목록 로드 실패: {exc}")
            self.plugin_list.addItem(item)
            return

        if not plugins:
            self.plugin_list.addItem(
                QListWidgetItem("플러그인이 없습니다. sample_plugin.py를 복사해 시작할 수 있습니다.")
            )
            return
        for plugin in plugins:
            label = f"{plugin.name} ({plugin.version}) - {plugin.description or '설명 없음'}"
            self.plugin_list.addItem(QListWidgetItem(label))

    def _installed_plugin_names(self) -> set[str]:
        try:
            from core.plugin_loader import get_plugin_manager
            return {plugin.name for plugin in get_plugin_manager().discover_plugins()}
        except Exception:
            return set()

    def _open_plugin_folder(self):
        path = self.plugin_dir_input.text().strip()
        if not path:
            return
        try:
            opened = QDesktopServices.openUrl(QUrl.fromLocalFile(path))
            if not opened:
                raise RuntimeError("폴더 열기 실패")
        except Exception:
            QMessageBox.information(self, "플러그인 폴더", path)

    # ── 마켓플레이스 ──────────────────────────────────────────────────────────

    def _refresh_marketplace_list(self):
        if self._market_fetch_thread and self._market_fetch_thread.isRunning():
            return

        self.marketplace_status_label.setText("마켓플레이스 목록을 불러오는 중...")
        self.marketplace_status_label.setStyleSheet("color: #888;")
        self.market_install_btn.setEnabled(False)
        self.marketplace_list.clear()

        self._market_fetch_thread = MarketplaceFetchThread(
            search=self.market_search_input.text(),
        )
        self._market_fetch_thread.done.connect(self._on_marketplace_fetch_done)
        self._market_fetch_thread.start()

    def _on_marketplace_fetch_done(self, success: bool, items: object, message: str):
        self._market_fetch_thread = None
        self.marketplace_list.clear()
        self._market_items = list(items) if isinstance(items, list) else []

        if not success:
            self.marketplace_status_label.setText(f"목록 로드 실패: {message}")
            self.marketplace_status_label.setStyleSheet("color: #e74c3c;")
            self.market_install_btn.setEnabled(False)
            return

        installed_names = self._installed_plugin_names()
        for item in self._market_items:
            name = str(item.get("name", "이름 없음"))
            version = str(item.get("version", "0.0.0"))
            install_count = int(item.get("install_count", 0) or 0)
            desc = str(item.get("description", "") or "설명 없음")
            status = "설치됨" if name in installed_names else "설치 가능"
            label = f"{name} v{version} [{status}] ({install_count} installs)\n{desc}"
            list_item = QListWidgetItem(label)
            list_item.setData(Qt.UserRole, item)
            self.marketplace_list.addItem(list_item)

        if self._market_items:
            self.marketplace_status_label.setText(f"{len(self._market_items)}개 플러그인을 불러왔습니다.")
            self.marketplace_status_label.setStyleSheet("color: #27ae60;")
            self.market_install_btn.setEnabled(True)
        else:
            self.marketplace_status_label.setText("표시할 플러그인이 없습니다.")
            self.marketplace_status_label.setStyleSheet("color: #888;")
            self.market_install_btn.setEnabled(False)

    def _install_selected_marketplace_plugin(self):
        item = self.marketplace_list.currentItem()
        if item is None:
            QMessageBox.information(self, "마켓플레이스", "설치할 플러그인을 먼저 선택하세요.")
            return

        payload = item.data(Qt.UserRole) or {}
        plugin_id = str(payload.get("id", "") or "")
        plugin_name = str(payload.get("name", "") or "플러그인")
        if not plugin_id:
            QMessageBox.warning(self, "마켓플레이스", "선택한 플러그인의 ID를 찾지 못했습니다.")
            return

        confirm = QMessageBox.question(
            self,
            "플러그인 설치",
            f"{plugin_name} 플러그인을 설치할까요?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes,
        )
        if confirm != QMessageBox.Yes:
            return

        self.market_install_btn.setEnabled(False)
        self.marketplace_status_label.setText(f"{plugin_name} 설치 중...")
        self.marketplace_status_label.setStyleSheet("color: #888;")

        self._market_install_thread = MarketplaceInstallThread(plugin_id)
        self._market_install_thread.done.connect(self._on_marketplace_install_done)
        self._market_install_thread.start()

    def _on_marketplace_install_done(self, success: bool, message: str):
        self._market_install_thread = None
        if success:
            self.marketplace_status_label.setText(message)
            self.marketplace_status_label.setStyleSheet("color: #27ae60;")
            self._refresh_plugin_list()
            self._refresh_marketplace_list()
            QMessageBox.information(self, "마켓플레이스", message)
        else:
            self.market_install_btn.setEnabled(True)
            self.marketplace_status_label.setText(message)
            self.marketplace_status_label.setStyleSheet("color: #e74c3c;")
            QMessageBox.warning(self, "마켓플레이스", message)

    # ── 공개 인터페이스 ────────────────────────────────────────────────────────

    def cleanup_threads(self):
        """다이얼로그 닫힐 때 실행 중인 스레드 정리."""
        for thread in (self._market_fetch_thread, self._market_install_thread):
            if thread and thread.isRunning():
                thread.quit()
                thread.wait(2000)
