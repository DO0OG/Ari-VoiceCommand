"""
Shimeji 스타일 캐릭터 위젯 (최적화 버전)
"""
import os
import random
import time
import sys
import logging
import ctypes
from collections import OrderedDict
from PySide6.QtWidgets import QWidget, QLabel, QMenu, QApplication
from PySide6.QtCore import Qt, QTimer, QPoint, QRect, QPropertyAnimation, QEasingCurve, QElapsedTimer, Signal, Slot, Property
from PySide6.QtGui import QPixmap, QImage, QCursor, QTransform, QAction
from speech_bubble import SpeechBubble, register_fonts
from constants import (
    GRAVITY, BOUNCE_Y, BOUNCE_X, FRICTION_GROUND, FRICTION_AIR,
    GREETING_INTERVAL, IMAGE_CACHE_CAPACITY
)


class LRUCache:
    """LRU 캐시 구현"""
    def __init__(self, capacity=IMAGE_CACHE_CAPACITY):
        self.cache = OrderedDict()
        self.capacity = capacity

    def get(self, key):
        if key not in self.cache:
            return None
        self.cache.move_to_end(key)
        return self.cache[key]

    def put(self, key, value):
        if key in self.cache:
            self.cache.move_to_end(key)
        self.cache[key] = value
        if len(self.cache) > self.capacity:
            self.cache.popitem(last=False)


class CharacterWidget(QWidget):
    # 스레드 안전한 시그널
    show_speech_bubble_signal = Signal(str, int)  # text, duration
    hide_speech_bubble_signal = Signal()
    change_emotion_signal = Signal(str)  # 추가: 감정 변경 시그널

    def get_char_x(self):
        return self.x()

    def set_char_x(self, x):
        self.move(x, self.y())

    char_x = Property(int, get_char_x, set_char_x)

    def __init__(self):
        super().__init__()
        register_fonts()  # 메인 스레드에서 폰트 등록
        self._screen_geom_cache = None
        self._screen_geom_cache_time = 0
        self.dragging = False
        self.offset = QPoint()
        self.target_pos = QPoint() # 드래그 시 목표 위치
        self.current_animation = "idle"
        self.frame_index = 0
        self.animations = {}
        self.image_cache = LRUCache()
        self.facing_right = True  # 캐릭터 방향

        # 물리 엔진
        self.velocity_x = 0
        self.velocity_y = 0
        self.gravity = GRAVITY
        self.is_falling = False
        self.is_climbing = False # 벽 타기 상태 추가
        self.climbing_direction = 0 # -1: 왼쪽 벽, 1: 오른쪽 벽
        self.drag_history = []

        # 탄성 및 마찰 계수
        self.bounce_y = BOUNCE_Y
        self.bounce_x = BOUNCE_X
        self.friction_ground = FRICTION_GROUND
        self.friction_air = FRICTION_AIR   

        # 마우스 추적
        self.mouse_tracker = QTimer(self)
        self.mouse_tracker.timeout.connect(self.track_mouse)
        self.mouse_tracker.start(100)
        self.mouse_tracking_enabled = False

        # 말풍선
        self.speech_bubble = None

        # 말풍선 자동 숨김 타이머
        self.bubble_hide_timer = QTimer(self)
        self.bubble_hide_timer.setSingleShot(True)
        self.bubble_hide_timer.timeout.connect(self._hide_speech_bubble_slot)

        # 시그널 연결
        self.show_speech_bubble_signal.connect(self._show_speech_bubble_slot)
        self.hide_speech_bubble_signal.connect(self._hide_speech_bubble_slot)
        self.change_emotion_signal.connect(self._change_emotion_slot)

        # 시간별 인사 타이머
        self.greeting_timer = QTimer(self)
        self.greeting_timer.timeout.connect(self.time_based_greeting)
        self.greeting_timer.start(GREETING_INTERVAL)

        # 윈도우 설정
        self.setWindowFlags(
            Qt.FramelessWindowHint |
            Qt.WindowStaysOnTopHint |
            Qt.Tool
        )
        self.setAttribute(Qt.WA_TranslucentBackground)

        # 애니메이션 로드
        self.load_animations()

        # 레이블 생성
        self.label = QLabel(self)
        self.update_frame()

        # 애니메이션 타이머 (속도 향상: 100ms -> 70ms)
        self.animation_timer = QTimer(self)
        self.animation_timer.timeout.connect(self.next_frame)
        self.animation_timer.start(70)

        # 행동 타이머 (3~10초마다)
        self.behavior_timer = QTimer(self)
        self.behavior_timer.timeout.connect(self.random_behavior)
        self.start_behavior_timer()

        # 이동 애니메이션
        self.move_animation = None

        # 물리 타이머 (30 FPS로 최적화)
        self.physics_timer = QTimer(self)
        self.physics_timer.timeout.connect(self.update_physics)
        self.physics_timer.start(33)

        # 화면 하단으로 이동
        self.move_to_bottom()
        self.show()

        # Windows에서 HWND_TOPMOST 강제 적용
        if sys.platform == 'win32':
            self._enforce_topmost()
            # 주기적으로 최상위 상태 재적용 (5초마다)
            self.topmost_timer = QTimer(self)
            self.topmost_timer.timeout.connect(self._enforce_topmost)
            self.topmost_timer.start(5000)

    def load_and_cache_image(self, path, flip=False, rotation=0):
        """이미지 로드, 캐싱 및 변형 (반전, 회전)"""
        cache_key = f"{path}_{'flip' if flip else 'normal'}_{rotation}"
        cached = self.image_cache.get(cache_key)
        if cached:
            return cached

        if not os.path.exists(path):
            return None

        image = QImage(path)
        if image.isNull():
            return None

        # 좌우 반전
        if flip:
            image = image.mirrored(True, False)
            
        # 회전
        if rotation != 0:
            transform = QTransform().rotate(rotation)
            image = image.transformed(transform, Qt.SmoothTransformation)

        scaled_image = image.scaled(
            int(image.width() * 1.5),
            int(image.height() * 1.5),
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation
        )

        pixmap = QPixmap.fromImage(scaled_image)
        self.image_cache.put(cache_key, pixmap)
        return pixmap

    def load_animations(self):
        """애니메이션 프레임 로드"""
        from resource_manager import ResourceManager

        animations = {
            "idle": 8,
            "walk": 9,
            "drag": 8,
            "fall": 8,
            "sit": 9,
            "climb": 6,
            "ceiling": 4,
            "sleep": 4,
            "surprised": 2
        }

        images_dir = ResourceManager.get_images_dir()  # 수정

        for anim_name, frame_count in animations.items():
            frames = []
            for i in range(1, frame_count + 1):
                img_path = os.path.join(images_dir, f"{anim_name}{i}.png")
                if os.path.exists(img_path):  # 존재 확인 추가
                    pixmap = self.load_and_cache_image(img_path)
                    if pixmap:
                        frames.append(img_path)  # 경로만 저장 (메모리 절약)

            if frames:
                self.animations[anim_name] = frames

    def get_screen_geometry(self):
        """화면 크기 정보를 캐싱하여 반환 (성능 최적화)"""
        if not hasattr(self, '_screen_geom_cache_time') or time.time() - self._screen_geom_cache_time > 2.0:
            self._screen_geom_cache = QApplication.primaryScreen().geometry()
            self._screen_geom_cache_time = time.time()
        return self._screen_geom_cache

    def get_ground_y(self):
        """현재 상태에 따른 바닥 Y 좌표 계산 (전체 화면 기준 및 오프셋 강화)"""
        screen = self.get_screen_geometry()
        ground_bottom = screen.height()
        # 앉은 자세(sit)는 이미지가 더 낮으므로 더 깊게 밀착 (공중에 뜨는 현상 방지)
        # idle: 0, sit: 25 (더 깊게 안착)
        offset = 25 if self.current_animation == "sit" else 5
        return ground_bottom - self.height() + offset

    def update_frame(self):
        """현재 프레임 업데이트 (자세 전환 시 위치 어긋남 방지)"""
        if self.current_animation in self.animations:
            frames = self.animations[self.current_animation]
            if frames:
                frame_path = frames[self.frame_index % len(frames)]
                flip = not self.facing_right
                pixmap = self.load_and_cache_image(frame_path, flip=flip)
                if pixmap:
                    # 새로운 프레임의 크기를 기준으로 위치와 크기를 한 번에 업데이트
                    screen = self.get_screen_geometry()
                    ground_bottom = screen.height()
                    offset = 25 if self.current_animation == "sit" else 5
                    new_y = ground_bottom - pixmap.height() + offset

                    self.label.setPixmap(pixmap)
                    self.label.adjustSize()
                    
                    # 바닥에 있을 때 위치와 크기를 동시에 변경
                    if not self.dragging and not self.is_falling:
                        # 좌우 경계 제한 (캐릭터 너비의 절반에서 15px 줄인 만큼만 화면 밖 허용)
                        margin = max(0, (pixmap.width() // 2) - 30)
                        new_x = max(-margin, min(self.x(), screen.width() - pixmap.width() + margin))
                        self.setGeometry(new_x, new_y, pixmap.width(), pixmap.height())
                    else:
                        self.setFixedSize(pixmap.width(), pixmap.height())

                    if self.speech_bubble:
                        self.speech_bubble.update_position()

    def next_frame(self):
        """다음 프레임으로"""
        if self.current_animation in self.animations:
            frame_count = len(self.animations[self.current_animation])
            self.frame_index = (self.frame_index + 1) % frame_count
            self.update_frame()

    def set_animation(self, animation_name):
        """애니메이션 변경"""
        if animation_name in self.animations and animation_name != self.current_animation:
            # 착지 중에는 애니메이션 강제 변경 방지 (자연스러운 전환을 위해)
            if getattr(self, '_is_landing', False) and animation_name not in ["sit", "idle"]:
                return
                
            self.current_animation = animation_name
            self.frame_index = 0
            self.update_frame()

    def start_behavior_timer(self):
        """랜덤 간격으로 행동 타이머 시작"""
        interval = random.randint(3000, 10000)  # 3~10초
        self.behavior_timer.start(interval)

    def random_behavior(self):
        """랜덤 행동 (벽 타기 확률 추가)"""
        if self.dragging or self.is_climbing or getattr(self, '_is_landing', False) or (self.move_animation and self.move_animation.state() == QPropertyAnimation.Running):
            self.start_behavior_timer()
            return

        screen = self.get_screen_geometry()
        margin = max(0, (self.width() // 2) - 30)
        # 벽 밀착 판정 (캐릭터 너비의 40% 이상 나갔을 때)
        at_left_edge = self.x() <= -margin + 10
        at_right_edge = self.x() >= screen.width() - self.width() + margin - 10

        # 벽 타기 시도 (화면 끝에서 30% 확률)
        if (at_left_edge or at_right_edge) and random.random() < 0.3:
            self.climbing_direction = -1 if at_left_edge else 1
            self.smooth_climb()
            return

        # 행동 선택 (확률 기반)
        rand = random.random()
        if rand < 0.4:
            behavior = "idle"
        elif rand < 0.6:
            behavior = "sit"
        elif rand < 0.75 and not (at_left_edge or at_right_edge):
            behavior = "walk"
        elif rand < 0.85:
            behavior = "sleep"
        else:
            behavior = "ceiling"

        self.set_animation(behavior)

        if behavior == "walk":
            self.smooth_walk()

        self.start_behavior_timer()

    def smooth_climb(self):
        """벽 타고 위로 올라가기"""
        self.is_climbing = True
        self.set_animation("climb")
        
        # 화면 높이의 20~50% 정도 위로 이동
        climb_height = random.randint(200, 500)
        new_y = max(50, self.y() - climb_height)

        if self.move_animation:
            self.move_animation.stop()

        self.move_animation = QPropertyAnimation(self, b"geometry")
        self.move_animation.setDuration(climb_height * 10) # 속도 조절
        self.move_animation.setStartValue(self.geometry())
        self.move_animation.setEndValue(QRect(self.x(), new_y, self.width(), self.height()))
        self.move_animation.setEasingCurve(QEasingCurve.Linear)
        self.move_animation.finished.connect(self.stop_climbing)
        self.move_animation.start()

    def stop_climbing(self):
        """벽 타기 중단 및 떨어지기"""
        self.is_climbing = False
        self.is_falling = True
        self.set_animation("fall")
        self.start_behavior_timer()

    def smooth_walk(self):
        """부드럽고 느린 걷기 이동"""
        from PySide6.QtWidgets import QApplication
        screen = self.get_screen_geometry()
        margin = max(0, (self.width() // 2) - 30)

        # 이동 거리 및 방향
        distance = random.randint(150, 400)
        direction = random.choice([-1, 1])
        new_x = self.x() + (distance * direction)

        # 화면 경계 체크 (벽 끝까지 이동 허용)
        new_x = max(-margin, min(new_x, screen.width() - self.width() + margin))

        # 캐릭터 방향 설정
        self.facing_right = (new_x > self.x())
        self.update_frame()

        # QPropertyAnimation 속도 늦춤 (1.5초 -> 4초)
        if self.move_animation:
            self.move_animation.stop()

        self.move_animation = QPropertyAnimation(self, b"char_x")
        self.move_animation.setDuration(4000) # 4초로 변경 (더 느릿하게)
        self.move_animation.setStartValue(self.x())
        self.move_animation.setEndValue(new_x)
        self.move_animation.setEasingCurve(QEasingCurve.InOutQuad)
        def on_walk_finished():
            self.set_animation("idle")
            if not self.dragging and not self.is_climbing:
                self.start_behavior_timer()
        self.move_animation.finished.connect(on_walk_finished)
        self.move_animation.start()

    def _enforce_topmost(self):
        """Win32 API로 항상 최상위 강제 적용 (Windows 전용)"""
        if sys.platform != 'win32':
            return
        try:
            HWND_TOPMOST = -1
            SWP_NOMOVE = 0x0002
            SWP_NOSIZE = 0x0001
            SWP_NOACTIVATE = 0x0010
            hwnd = int(self.winId())
            ctypes.windll.user32.SetWindowPos(
                hwnd, HWND_TOPMOST, 0, 0, 0, 0,
                SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE
            )
        except Exception:
            pass

    def showEvent(self, event):
        super().showEvent(event)
        if sys.platform == 'win32':
            QTimer.singleShot(100, self._enforce_topmost)

    def move_to_bottom(self):
        """화면 하단으로 이동"""
        screen = self.get_screen_geometry()
        x = random.randint(0, max(0, screen.width() - 200))
        # 캐릭터 크기를 고려한 바닥 위치 (약 150px 높이 예상)
        y = screen.height() - 200  # 하단에서 200px 위
        self.move(x, y)

    def mousePressEvent(self, event):
        """마우스 클릭"""
        if event.button() == Qt.LeftButton:
            # 더블클릭 감지
            if not hasattr(self, '_last_click'):
                self._last_click = 0
            now = time.time()
            if now - self._last_click < 0.3:
                reactions = ["왜요?", "뭐예요?", "네?", "간지러워요!", "헤헤"]
                self.say(random.choice(reactions), duration=2000)
                self.set_animation("surprised")
                QTimer.singleShot(1000, lambda: self.set_animation("idle"))
                self._last_click = 0
                return
            self._last_click = now

            self.dragging = True
            self._is_landing = False # 드래그 시 착지 플래그 초기화
            self.offset = event.globalPos() - self.pos()
            self.set_animation("drag")

            self.velocity_x = 0
            self.velocity_y = 0
            self.drag_history = [(event.globalPos(), time.time())]

            if self.move_animation:
                self.move_animation.stop()

            self.physics_timer.stop()
            self.behavior_timer.stop()

    def mouseMoveEvent(self, event):
        """마우스 드래그 (즉각적인 1:1 이동 및 방향 전환)"""
        if self.dragging:
            # 목표 위치 계산 (Lerp 제거, 즉시 이동)
            nx = event.globalPos().x() - self.offset.x()
            ny = event.globalPos().y() - self.offset.y()
            
            # 화면 경계 제한 (좌우는 절반까지 밖으로, 상단은 0, 하단은 바닥까지)
            screen = self.get_screen_geometry()
            margin = max(0, (self.width() // 2) - 30)
            nx = max(-margin, min(nx, screen.width() - self.width() + margin))
            ny = max(0, min(ny, screen.height() - self.height() + 25))

            # 방향 감지 및 프레임 업데이트
            dx = nx - self.x()
            if abs(dx) > 2: # 최소 이동 거리 기준
                self.facing_right = (dx > 0)
                self.update_frame()

            self.move(nx, ny)
            
            # 히스토리 기록
            self.drag_history.append((event.globalPos(), time.time()))
            if len(self.drag_history) > 5:
                self.drag_history.pop(0)

            # 말풍선 위치 업데이트
            if self.speech_bubble:
                self.speech_bubble.update_position()

    def mouseReleaseEvent(self, event):
        """마우스 릴리즈"""
        if event.button() == Qt.LeftButton:
            self.dragging = False

            # 타이머 재시작
            self.animation_timer.start(100)
            self.physics_timer.start(33)
            self.start_behavior_timer()

            # 던지기 속도 계산 (계수 0.02로 약간 약화시켜 안정성 확보)
            current_time = time.time()
            valid_history = [h for h in self.drag_history if current_time - h[1] < 0.2]
            
            if len(valid_history) >= 2:
                old_pos, old_time = valid_history[0]
                curr_pos, curr_time = valid_history[-1]
                dt = curr_time - old_time
                if dt > 0:
                    vx = (curr_pos.x() - old_pos.x()) / dt * 0.02
                    vy = (curr_pos.y() - old_pos.y()) / dt * 0.02
                    self.velocity_x = max(-25, min(25, vx))
                    self.velocity_y = max(-25, min(25, vy))
            else:
                self.velocity_x = 0
                self.velocity_y = 0

            self.is_falling = True
            self.set_animation("fall")
            # 릴리즈 후 일정 시간 뒤에 idle로 (강제 착지 연출 방지)
            QTimer.singleShot(800, lambda: self.set_animation("idle") if not self.dragging and not self.is_falling and not getattr(self, '_is_landing', False) else None)

    def set_text_interface(self, text_interface):
        """텍스트 인터페이스 참조 설정"""
        self.text_interface = text_interface

    def open_text_interface(self):
        """텍스트 대화창 열기 (캐릭터 위치 기준)"""
        if hasattr(self, 'text_interface') and self.text_interface:
            self.text_interface.show_near(self.x(), self.y(), self.width(), self.height())

    def contextMenuEvent(self, event):
        """우클릭 메뉴"""
        from VoiceCommand import learning_mode
        menu = QMenu(self)

        # 텍스트 대화
        chat_action = QAction("💬 텍스트 대화", self)
        chat_action.triggered.connect(self.open_text_interface)
        menu.addAction(chat_action)

        menu.addSeparator()

        # 설정
        settings_action = QAction("설정", self)
        settings_action.triggered.connect(self.open_settings)
        menu.addAction(settings_action)

        menu.addSeparator()

        # 게임 모드
        from VoiceCommand import is_game_mode, enable_game_mode, disable_game_mode
        game_action = QAction("🎮 게임 모드 (GPU 절약)", self)
        game_action.setCheckable(True)
        game_action.setChecked(is_game_mode())
        def toggle_game_mode(checked):
            if checked:
                enable_game_mode()
                self.say("게임 모드 ON. GPU 메모리 해제했습니다.", duration=3000)
            else:
                disable_game_mode()
                self.say("게임 모드 OFF. TTS 복원 중...", duration=3000)
        game_action.triggered.connect(toggle_game_mode)
        menu.addAction(game_action)

        # 스마트 어시스턴트 모드
        smart_action = QAction("스마트 어시스턴트 모드", self)
        smart_action.setCheckable(True)
        smart_action.setChecked(learning_mode['enabled'])
        def toggle_smart_mode(checked):
            learning_mode['enabled'] = checked
            if checked:
                self.say("스마트 어시스턴트 모드가 활성화되었습니다.", duration=3000)
            else:
                self.say("스마트 어시스턴트 모드가 비활성화되었습니다.", duration=3000)
        smart_action.triggered.connect(toggle_smart_mode)
        menu.addAction(smart_action)

        # 마우스 반응
        mouse_action = QAction("마우스 반응", self)
        mouse_action.setCheckable(True)
        mouse_action.setChecked(self.mouse_tracking_enabled)
        mouse_action.triggered.connect(self.toggle_mouse_tracking)
        menu.addAction(mouse_action)

        # 숨기기
        hide_action = QAction("숨기기", self)
        hide_action.triggered.connect(self.hide)
        menu.addAction(hide_action)

        menu.addSeparator()

        # 종료
        exit_action = QAction("종료", self)
        exit_action.triggered.connect(self.exit_program)
        menu.addAction(exit_action)

        menu.exec(event.globalPos())

    def toggle_mouse_tracking(self):
        """마우스 추적 토글"""
        self.mouse_tracking_enabled = not self.mouse_tracking_enabled

    def open_settings(self):
        """설정 창 열기"""
        from settings_dialog import SettingsDialog
        dialog = SettingsDialog()
        if dialog.exec():
            from VoiceCommand import initialize_tts
            initialize_tts()

    def exit_program(self):
        """프로그램 종료 요청"""
        logging.info("캐릭터 메뉴를 통한 프로그램 종료 요청")
        app = QApplication.instance()
        if app:
            app.quit()

    def update_physics(self):
        """물리 엔진 (착지 판정 및 모션 싱크 강화)"""
        if self.dragging:
            return

        screen = self.get_screen_geometry()
        target_y = self.get_ground_y()
        current_y = self.y()
        moved = False

        # 중력 적용 로직 (오차 허용 범위 내)
        if current_y < target_y - 40 or self.velocity_y < 0:
            self.is_falling = True
            self.velocity_y = min(self.velocity_y + self.gravity, 20)
            new_y = current_y + self.velocity_y

            # 착지 판정
            if new_y >= target_y:
                new_y = target_y
                # 착지 직전 속도 저장
                impact_vel = abs(self.velocity_y)
                
                if impact_vel > 3:
                    self.velocity_y *= self.bounce_y
                else:
                    self.velocity_y = 0
                    self.is_falling = False
                    
                    # 스마트 착지 연출: 낙하 속도가 빠를 때만 sit(충격흡수) 적용
                    if self.current_animation == "fall":
                        if impact_vel > 8: # 강한 추락 기준
                            self._is_landing = True
                            self.set_animation("sit")
                            def finish_landing():
                                self._is_landing = False
                                if not self.is_falling and not self.dragging:
                                    self.set_animation("idle")
                            QTimer.singleShot(600, finish_landing)
                        else: # 살짝 떨어짐
                            self.set_animation("idle")

            if int(new_y) != current_y:
                self.setGeometry(self.x(), int(new_y), self.width(), self.height())
                moved = True

        else:
            # 바닥에 안정적으로 붙어있을 때
            if self.is_falling or self.current_animation == "fall":
                self.is_falling = False
                self._is_landing = True
                self.set_animation("sit")
                def finish_landing():
                    self._is_landing = False
                    if not self.is_falling and not self.dragging:
                        self.set_animation("idle")
                QTimer.singleShot(700, finish_landing)
            
            self.velocity_y = 0

        # 수평 이동 (던지기 및 마찰)
        if self.velocity_x != 0:
            new_x = int(self.x() + self.velocity_x)
            margin = max(0, (self.width() // 2) - 30)
            
            # 벽 충돌 및 튕기기 (화면 밖 절반까지 허용)
            if new_x < -margin:
                new_x = -margin
                self.velocity_x *= self.bounce_x
            elif new_x > screen.width() - self.width() + margin:
                new_x = screen.width() - self.width() + margin
                self.velocity_x *= self.bounce_x

            if new_x != self.x():
                self.move(new_x, self.y())
                moved = True

            # 마찰 적용
            if self.is_falling:
                self.velocity_x *= self.friction_air
            else:
                self.velocity_x *= self.friction_ground
                
            if abs(self.velocity_x) < 0.5:
                self.velocity_x = 0

        # 말풍선 위치 업데이트
        if moved and self.speech_bubble:
            self.speech_bubble.update_position()

    def track_mouse(self):
        """마우스 반응 — 거리에 따라 호기심/도망 행동"""
        if not self.mouse_tracking_enabled or self.dragging or self.is_climbing:
            return

        cursor_pos = QCursor.pos()
        char_center = self.geometry().center()

        dx = cursor_pos.x() - char_center.x()
        distance = abs(dx)

        screen = self.get_screen_geometry()
        margin = max(0, (self.width() // 2) - 30)
        at_edge = self.x() <= -margin + 5 or self.x() >= screen.width() - self.width() + margin - 5

        if distance < 80:
            # 매우 가까움 — 놀라서 도망 (속도 강하게)
            if not getattr(self, '_mouse_scared', False):
                self._mouse_scared = True
                self.set_animation("surprised")
                QTimer.singleShot(400, lambda: self.set_animation("walk") if self.mouse_tracking_enabled else None)

            if not at_edge:
                # 반대 방향으로 velocity 부여 (물리 엔진에 위임)
                self.velocity_x = -8 if dx > 0 else 8
                self.facing_right = (self.velocity_x > 0)
            else:
                # 벽에 몰렸을 때 — 벽 타기로 탈출
                if not self.is_climbing:
                    self.smooth_climb()

        elif distance < 200:
            # 중간 거리 — 슬슬 걷기로 피함
            self._mouse_scared = False
            if not at_edge and not self.is_falling:
                self.velocity_x = -3 if dx > 0 else 3
                self.facing_right = (self.velocity_x > 0)
                self.set_animation("walk")

        else:
            # 멀면 — 평상시로 복귀
            self._mouse_scared = False

    def set_emotion(self, emotion):
        """감정 설정 (외부에서 호출 - 스레드 안전)"""
        self.change_emotion_signal.emit(emotion)

    @Slot(str)
    def _change_emotion_slot(self, emotion):
        """실제 감정 표현 처리 (메인 스레드)"""
        logging.debug(f"캐릭터 감정 표현: {emotion}")
        
        # 감정에 따른 애니메이션 매핑
        emotion_map = {
            "기쁨": ["walk", "idle"],
            "슬픔": ["sit", "sleep"],
            "화남": ["surprised"],
            "놀람": ["surprised"],
            "평온": ["idle", "sit"],
            "수줍": ["sit", "idle"],
            "기대": ["walk", "idle"],
            "진지": ["sit"],
            "걱정": ["sit", "idle"]
        }
        
        if emotion in emotion_map:
            anim = random.choice(emotion_map[emotion])
            self.set_animation(anim)
            
            # 기쁨/기대일 경우 가볍게 점프 효과
            if emotion in ["기쁨", "기대"] and not self.is_falling:
                self.velocity_y = -8
                self.is_falling = True

    def say(self, text, duration=5000):
        """말풍선 표시 (외부에서 호출 - 스레드 안전)"""
        # 시그널로 전달 (어느 스레드에서든 안전)
        self.show_speech_bubble_signal.emit(text, duration)

    @Slot(str, int)
    def _show_speech_bubble_slot(self, text, duration):
        """실제 말풍선 표시 (메인 스레드에서만 실행)"""
        # 기존 타이머 정지
        self.bubble_hide_timer.stop()

        # 기존 말풍선 제거
        if self.speech_bubble:
            self.speech_bubble.hide()
            self.speech_bubble.deleteLater()

        # 새 말풍선 생성
        self.speech_bubble = SpeechBubble(text, self)
        self.speech_bubble.show()
        self.speech_bubble.raise_()
        self.update()

        # 자동 숨김 타이머 시작 (메인 스레드에서)
        if duration > 0:
            self.bubble_hide_timer.start(duration)
        else:
            # duration=0 (TTS 대기)인 경우에도 최대 60초 후에는 사라지도록 안전장치 설정 (긴 문장 대응)
            self.bubble_hide_timer.start(60000)
            logging.debug("말풍선 대기 모드 (60초 안전장치 작동)")

    def hide_speech_bubble(self):
        """말풍선 숨기기 (외부에서 호출)"""
        self.hide_speech_bubble_signal.emit()

    @Slot()
    def _hide_speech_bubble_slot(self):
        """실제 말풍선 숨김 (메인 스레드에서만 실행)"""
        if self.speech_bubble:
            logging.debug("말풍선 숨김 처리")
            self.speech_bubble.hide()
            self.speech_bubble.deleteLater()
            self.speech_bubble = None
        self.bubble_hide_timer.stop()

    def time_based_greeting(self):
        """시간대별 인사"""
        from datetime import datetime
        hour = datetime.now().hour

        greetings = {
            (6, 11): ["좋은 아침이에요!", "잘 주무셨어요?", "아침이네요!"],
            (12, 13): ["점심 시간이에요!", "맛있게 드세요!"],
            (14, 17): ["오후네요~", "힘내세요!"],
            (18, 21): ["저녁 시간이에요", "하루 어떠셨어요?"],
            (22, 23): ["밤이 깊었어요", "이제 쉬세요~"],
            (0, 5): ["늦은 시간이네요", "푹 쉬세요!"]
        }

        for (start, end), messages in greetings.items():
            if start <= hour <= end:
                message = random.choice(messages)
                self.say(message, duration=4000)
                break

    def cleanup(self):
        """정리"""
        if self.animation_timer:
            self.animation_timer.stop()
        if self.behavior_timer:
            self.behavior_timer.stop()
        if self.move_animation:
            self.move_animation.stop()
        if self.physics_timer:
            self.physics_timer.stop()
        if self.mouse_tracker:
            self.mouse_tracker.stop()
        if hasattr(self, 'greeting_timer'):
            self.greeting_timer.stop()
        if hasattr(self, 'bubble_hide_timer'):
            self.bubble_hide_timer.stop()
        if self.speech_bubble:
            self.speech_bubble.close()
        self.image_cache.cache.clear()
        self.close()
