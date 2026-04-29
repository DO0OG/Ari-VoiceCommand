import unittest

from commands.base_command import CommandResult
from commands.weather_command import WeatherCommand


class _WeatherService:
    def get_weather_from_text(self, text):
        return f"weather:{text}"


class WeatherCommandTests(unittest.TestCase):
    def test_matches_english_and_japanese_weather_keywords(self):
        command = WeatherCommand(_WeatherService(), lambda _msg: None)

        self.assertTrue(command.matches("weather forecast please"))
        self.assertTrue(command.matches("東京の天気"))

    def test_execute_returns_command_result(self):
        spoken = []
        command = WeatherCommand(_WeatherService(), spoken.append)

        result = command.execute("weather")

        self.assertIsInstance(result, CommandResult)
        self.assertTrue(result.success)
        self.assertEqual(result.response, "weather:weather")
        self.assertEqual(spoken, ["weather:weather"])


if __name__ == "__main__":
    unittest.main()
