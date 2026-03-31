"""설정창용 마켓플레이스 조회/설치 스레드."""
from __future__ import annotations

from PySide6.QtCore import QThread, Signal


class MarketplaceFetchThread(QThread):
    done = Signal(bool, object, str)

    def __init__(self, search: str = "", sort: str = "install_count"):
        super().__init__()
        self.search = search.strip()
        self.sort = sort

    def run(self):
        try:
            from core.marketplace_client import fetch_plugins

            items = fetch_plugins(search=self.search, sort=self.sort)
            self.done.emit(True, items, "")
        except Exception as exc:
            self.done.emit(False, [], str(exc))


class MarketplaceInstallThread(QThread):
    done = Signal(bool, str)

    def __init__(self, plugin_id: str):
        super().__init__()
        self.plugin_id = plugin_id

    def run(self):
        try:
            from core.marketplace_client import install_plugin

            ok = install_plugin(self.plugin_id)
            if ok:
                self.done.emit(True, "플러그인 설치가 완료되었습니다.")
            else:
                self.done.emit(False, "플러그인 설치에 실패했습니다.")
        except Exception as exc:
            self.done.emit(False, str(exc))
