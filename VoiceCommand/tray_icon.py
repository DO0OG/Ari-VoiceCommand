import logging
from PySide6.QtWidgets import QApplication, QSystemTrayIcon, QMenu, QDialog
from settings_dialog import SettingsDialog

class SystemTrayIcon(QSystemTrayIcon):
    def __init__(self, icon, parent=None):
        super(SystemTrayIcon, self).__init__(icon, parent)
        self.setToolTip("Ari Voice Command")
        self.should_exit = False
        self.character_widget = None
        self.text_interface = None

        self.menu = QMenu(parent)
        self.setContextMenu(self.menu)

        self.chat_action = self.menu.addAction("💬 텍스트 대화")
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

        self.menu.addSeparator()

        self.settings_action = self.menu.addAction("설정")
        self.settings_action.triggered.connect(self.open_settings)

        self.menu.addSeparator()

        self.exit_action = self.menu.addAction("종료")
        self.exit_action.triggered.connect(self.exit)

        self.menu.aboutToShow.connect(self.update_character_menu_text)
        self.menu.aboutToShow.connect(self.update_game_mode_status)
        self.menu.aboutToShow.connect(self.update_smart_mode_status)
        self.menu.aboutToShow.connect(self.update_mouse_reaction_status)

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
            from VoiceCommand import initialize_tts, _tts_init_event
            import threading
            _tts_init_event.clear()
            def _reinit():
                try:
                    initialize_tts()
                except Exception as e:
                    logging.error(f"TTS 재초기화 실패: {e}")
            threading.Thread(target=_reinit, daemon=True, name="TTS-Reinit").start()
            logging.info("설정이 저장되고 TTS 재초기화를 시작했습니다.")

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
