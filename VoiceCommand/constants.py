"""프로젝트 상수 정의"""

# 음성 인식 설정
SPEECH_LANGUAGE = "ko-KR"
SPEECH_TIMEOUT = 5  # 초
SPEECH_PHRASE_LIMIT = 5  # 초
AMBIENT_NOISE_DURATION = 0.5  # 초

# 웨이크워드
WAKE_WORDS = ["아리야", "시작"]
WAKE_RESPONSES = ["네?", "부르셨나요?"]

# 캐릭터 물리 설정
GRAVITY = 0.8
BOUNCE_Y = -0.2
BOUNCE_X = -0.3
FRICTION_GROUND = 0.85
FRICTION_AIR = 0.99

# 타이머
GREETING_INTERVAL = 1800000  # 30분 (밀리초)

# TTS 설정
DEFAULT_TTS_SPEED = 1.0
DEFAULT_TTS_VOLUME = 1.0

# 파일 경로
SETTINGS_FILE = "ari_settings.json"
CONFIG_FILE = "config.json"
LOG_DIR = "logs"
CACHE_DIR = "tts_cache"

# 캐시 설정
IMAGE_CACHE_CAPACITY = 20
