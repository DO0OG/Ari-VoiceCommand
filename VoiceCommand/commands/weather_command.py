"""날씨 명령"""
from commands.base_command import BaseCommand
import logging


class WeatherCommand(BaseCommand):
    """날씨 정보 명령"""

    def __init__(self, weather_service, tts_func):
        self.weather_service = weather_service
        self.tts_wrapper = tts_func

    def matches(self, text: str) -> bool:
        return "날씨 어때" in text

    def execute(self, text: str) -> None:
        try:
            weather_info = self.weather_service.get_weather()
            self.tts_wrapper(weather_info)
        except Exception as e:
            logging.error(f"날씨 정보 조회 중 오류 발생: {str(e)}")
            self.tts_wrapper("날씨 정보를 가져오는 데 실패했습니다.")
