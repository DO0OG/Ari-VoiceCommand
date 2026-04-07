"""시스템 트레이 메뉴와 설정 대화상자 진입점을 제공하는 UI 래퍼."""

import logging
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QApplication, QSystemTrayIcon, QMenu, QDialog
from ui.settings_dialog import SettingsDialog
from i18n.translator import _

class SystemTrayIcon(QSystemTrayIcon):
    def __init__(self, icon, parent=None):
        super(SystemTrayIcon, self).__init__(icon, parent)
        self.setToolTip("Ari Voice Command")
        self.should_exit = False
        self.character_widget = None
        self.text_interface = None
        self._scheduled_tasks_dialog = None

        self.menu = QMenu(parent)
        self._apply_menu_theme()
        self.setContextMenu(self.menu)

        self.chat_action = self.menu.addAction(_("💬 텍스트 대화"))
        self.chat_action.triggered.connect(self.open_text_interface)

        self.character_action = self.menu.addAction("캐릭터 표시")
        self.character_action.triggered.connect(self.toggle_character)

        self.menu.addSeparator()

        self.game_mode_action = self.menu.addAction("🎮 게임 모드 (GPU 절약)")
        self.game_mode_action.setCheckable(True)
        self.game_mode_action.triggered.connect(self.toggle_game_mode)

        self.smart_mode_action = self.menu.addAction("스마트 어시스턴트 모드")
        self.smart_mode_action.setCheckable(True)
        self.smart_mode_action.triggered.connect(self.toggle_smart_mode)

        self.mouse_reaction_action = self.menu.addAction("마우스 반응")
        self.mouse_reaction_action.setCheckable(True)
        self.mouse_reaction_action.triggered.connect(self.toggle_mouse_reaction)

        self._plugin_separator = self.menu.addSeparator()
        self._plugin_actions: list = []

        self.settings_action = self.menu.addAction(_("설정"))
        self.settings_action.triggered.connect(self.open_settings)

        self.scheduled_tasks_action = self.menu.addAction("예약 작업 관리")
        self.scheduled_tasks_action.triggered.connect(self.open_scheduled_tasks)

        self.menu.addSeparator()

        self.exit_action = self.menu.addAction(_("종료"))
        self.exit_action.triggered.connect(self.exit)

        self.menu.aboutToShow.connect(self.update_character_menu_text)
        self.menu.aboutToShow.connect(self.update_game_mode_status)
        self.menu.aboutToShow.connect(self.update_smart_mode_status)
        self.menu.aboutToShow.connect(self.update_mouse_reaction_status)
        self.menu.aboutToShow.connect(self._apply_menu_theme)

    def add_plugin_menu_action(self, label: str, callback) -> None:
        """플러그인이 트레이 메뉴에 항목을 추가하는 공개 API."""
        action = QAction(label, self.menu)
        action.triggered.connect(callback)
        self.menu.insertAction(self.settings_action, action)
        self._plugin_actions.append(action)
        return action

    def remove_plugin_menu_action(self, action) -> None:
        if action in self._plugin_actions:
            self._plugin_actions.remove(action)
        self.menu.removeAction(action)
        action.deleteLater()

    def _apply_menu_theme(self):
        from ui import theme as theme_module
        self.menu.setStyleSheet(theme_module.MENU_STYLE)

    def toggle_game_mode(self):
        from VoiceCommand import enable_game_mode, disable_game_mode
        if self.game_mode_action.isChecked():
            enable_game_mode()
            if self.character_widget:
                self.character_widget.say("게임 모드 ON. GPU 메모리 해제했습니다.", duration=3000)
        else:
            disable_game_mode()
            if self.character_widget:
                self.character_widget.say("게임 모드 OFF. TTS 복원 중...", duration=3000)

    def update_game_mode_status(self):
        from VoiceCommand import is_game_mode
        self.game_mode_action.setChecked(is_game_mode())

    def toggle_smart_mode(self):
        from VoiceCommand import learning_mode
        learning_mode['enabled'] = self.smart_mode_action.isChecked()
        status = "활성화" if learning_mode['enabled'] else "비활성화"
        logging.info(f"스마트 어시스턴트 모드 {status}")
        if self.character_widget:
            message = f"스마트 어시스턴트 모드가 {status}되었습니다."
            self.character_widget.say(message, duration=3000)

    def update_smart_mode_status(self):
        from VoiceCommand import learning_mode
        self.smart_mode_action.setChecked(learning_mode['enabled'])

    def toggle_mouse_reaction(self):
        if self.character_widget:
            self.character_widget.toggle_mouse_tracking()

    def update_mouse_reaction_status(self):
        if self.character_widget:
            self.mouse_reaction_action.setChecked(self.character_widget.mouse_tracking_enabled)

    def open_settings(self):
        dialog = SettingsDialog()
        if dialog.exec() == QDialog.Accepted:
            if dialog.tts_settings_changed():
                from VoiceCommand import initialize_tts, _tts_init_event
                import threading
                _tts_init_event.clear()

                def _reinit():
                    try:
                        initialize_tts()
                    except Exception as e:
                        logging.error(f"TTS 재초기화 실패: {e}")

                threading.Thread(target=_reinit, daemon=True, name="TTS-Reinit").start()
                logging.info("TTS 관련 설정이 변경되어 TTS 재초기화를 시작했습니다.")

            if dialog.theme_settings_changed():
                try:
                    from ui.theme_runtime import apply_live_theme
                    apply_live_theme(tray_icon=self, character_widget=self.character_widget)
                except Exception as e:
                    logging.error(f"실시간 테마 반영 실패: {e}")


    def open_scheduled_tasks(self):
        try:
            from agent.proactive_scheduler import get_scheduler
            from ui.scheduled_tasks_dialog import ScheduledTasksDialog

            if self._scheduled_tasks_dialog is None:
                self._scheduled_tasks_dialog = ScheduledTasksDialog(get_scheduler())
            self._scheduled_tasks_dialog.show()
            self._scheduled_tasks_dialog.raise_()
            self._scheduled_tasks_dialog.activateWindow()
        except Exception as e:
            logging.error(f"예약 작업 창 열기 실패: {e}")

    def exit(self):
        self.should_exit = True
        QApplication.instance().quit()

    def set_character_widget(self, character_widget):
        self.character_widget = character_widget
        self.update_character_menu_text()
        logging.info("시스템 트레이에 캐릭터 위젯 참조가 설정되었습니다.")

    def set_text_interface(self, text_interface):
        self.text_interface = text_interface

    def open_text_interface(self):
        if self.text_interface:
            screen = QApplication.primaryScreen().geometry()
            self.text_interface.show_near(screen.width() - 100, screen.height() - 100, 0, 0)

    def toggle_character(self):
        if not self.character_widget:
            logging.warning("캐릭터 위젯이 초기화되지 않았습니다.")
            return
        if self.character_widget.isVisible():
            self.character_widget.hide()
            logging.info("캐릭터를 숨겼습니다.")
        else:
            self.character_widget.show()
            logging.info("캐릭터를 표시했습니다.")

    def update_character_menu_text(self):
        if self.character_widget and self.character_widget.isVisible():
            self.character_action.setText("캐릭터 숨기기")
        else:
            self.character_action.setText("캐릭터 표시")
