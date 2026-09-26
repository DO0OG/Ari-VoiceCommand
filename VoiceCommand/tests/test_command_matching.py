import unittest

from commands.calculator_command import CalculatorCommand
from commands.time_command import TimeCommand
from commands.volume_command import VolumeCommand


class LegacyCommandMatchingTests(unittest.TestCase):
    def test_time_command_leaves_other_places_and_compound_requests(self):
        command = TimeCommand(lambda _msg: None)

        self.assertTrue(command.matches("지금 몇 시야"))
        self.assertFalse(command.matches("파리는 지금 몇 시야"))
        self.assertFalse(command.matches("지금 몇 시야 그리고 볼륨 올려줘"))

    def test_volume_command_uses_parsed_amount_and_leaves_compound_requests(self):
        calls = []
        command = VolumeCommand(
            lambda change, amount=None: calls.append((change, amount)),
            lambda _msg: None,
        )

        self.assertFalse(command.matches("볼륨 올리고 캡처해줘"))
        self.assertFalse(command.matches("볼륨 올리지 마"))
        for text in ("볼륨 10 내려 줘", "볼륨 키우기", "볼륨 음소거 해제"):
            self.assertTrue(command.matches(text))
            command.execute(text)

        self.assertEqual(calls, [("down", 10), ("up", None), ("unmute", None)])

    def test_calculator_needs_numeric_expression(self):
        spoken = []
        command = CalculatorCommand(spoken.append)

        self.assertFalse(command.matches("바탕 화면에 테스트 좀 txt 파일 만들고"))
        self.assertFalse(command.matches("계산기 열어줘"))
        self.assertTrue(command.matches("3 곱하기 4는?"))
        command.execute("3 곱하기 4는?")

        self.assertIn("12입니다", spoken[0])


if __name__ == "__main__":
    unittest.main()
