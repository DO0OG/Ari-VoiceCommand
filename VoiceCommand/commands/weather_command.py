"""날씨 명령"""
from commands.base_command import BaseCommand, CommandResult
import logging
from i18n.translator import _


class WeatherCommand(BaseCommand):
    """날씨 정보 명령"""
    _WEATHER_KEYWORDS = (
        "날씨", "기온", "비와", "비와?", "비와요", "온도",
        "weather", "temperature", "rain", "forecast",
        "天気", "気温", "雨",
    )

    def __init__(self, weather_service, tts_func):
        self.weather_service = weather_service
        self.tts_wrapper = tts_func

    def matches(self, text: str) -> bool:
        normalized = (text or "").replace(" ", "").lower()
        return any(keyword.lower() in normalized for keyword in self._WEATHER_KEYWORDS)

    def execute(self, text: str) -> CommandResult:
        try:
            weather_info = self.weather_service.get_weather_from_text(text)
            self.tts_wrapper(weather_info)
            return CommandResult(success=True, response=str(weather_info or ""))
        except Exception as e:
            logging.error("날씨 정보 조회 중 오류 발생: %s", e)
            message = _("날씨 정보를 가져오는 데 실패했습니다.")
            self.tts_wrapper(message)
            return CommandResult(success=False, response=message, data={"error": str(e)})
