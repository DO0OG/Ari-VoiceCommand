import unittest
from unittest.mock import patch

from commands.calculator_command import CalculatorCommand
from commands.system_command import SystemCommand
from commands.time_command import TimeCommand
from commands.volume_command import VolumeCommand
from i18n.translator import _


class LegacyCommandMatchingTests(unittest.TestCase):
    def test_system_command_only_takes_whole_power_commands(self):
        command = SystemCommand(lambda _msg: None)

        for text in ("컴퓨터 좀 꺼 줘", "10분 뒤에 컴퓨터 종료해줘", "재부팅", "종료 취소"):
            self.assertTrue(command.matches(text), text)
        for text in (
            "재부팅하지 마",
            "컴퓨터 종료 방법 알려줘",
            "모니터 전원 꺼줘",
            "시스템 설정 창 꺼줘",
            "npc 대화창 꺼줘",
            "how do I restart my router",
        ):
            self.assertFalse(command.matches(text), text)

    def test_system_command_cancel_does_not_restart(self):
        command = SystemCommand(lambda _msg: None)

        with patch.object(command, "_cancel_shutdown") as cancel, patch.object(command, "_restart_immediate") as restart:
            command.execute("재부팅 취소")

        cancel.assert_called_once()
        restart.assert_not_called()

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


class SystemCommandConfirmationTests(unittest.TestCase):
    """종료·재시작은 OS 호출 전에 확인을 받고, 종료 취소는 확인 없이 처리한다."""

    CASES = (
        ("컴퓨터 꺼줘", "종료", "지금 바로"),
        ("컴퓨터 재시작해줘", "재시작", "지금 바로"),
        ("5분 뒤에 컴퓨터 꺼줘", "종료", None),
        ("5분 뒤에 컴퓨터 재시작해줘", "재시작", None),
    )

    def _run(self, text, confirm_result):
        spoken = []
        command = SystemCommand(spoken.append)
        with patch("agent.confirmation_manager.get_confirmation_manager") as get_manager, \
                patch("commands.system_command.subprocess.run") as run:
            get_manager.return_value.request_confirmation.return_value = confirm_result
            command.execute(text)
        return get_manager.return_value.request_confirmation, run, spoken

    def test_approved_power_command_runs_os_call_exactly_once(self):
        for text, action, when in self.CASES:
            with self.subTest(text=text):
                confirm, run, _spoken = self._run(text, True)
                confirm.assert_called_once()
                desc, report = confirm.call_args.args[:2]
                self.assertIn(_(action), desc)
                self.assertEqual(report.category, "power")
                if when:
                    self.assertIn(_(when), desc)
                run.assert_called_once()
                self.assertEqual(run.call_args.args[0][0], "shutdown")

    def test_denied_or_timed_out_power_command_makes_no_os_call(self):
        for text, action, _when in self.CASES:
            for answer in (False, None):
                with self.subTest(text=text, answer=answer):
                    confirm, run, spoken = self._run(text, answer)
                    confirm.assert_called_once()
                    run.assert_not_called()
                    self.assertEqual(
                        spoken[-1],
                        _("컴퓨터 종료 요청을 취소했어요.") if action == "종료" else _("컴퓨터 재시작 요청을 취소했어요."))

    def test_confirmation_failure_is_treated_as_denied(self):
        spoken = []
        command = SystemCommand(spoken.append)
        with patch("agent.confirmation_manager.get_confirmation_manager", side_effect=RuntimeError("no ui")), \
                patch("commands.system_command.subprocess.run") as run:
            command.execute("컴퓨터 꺼줘")
        run.assert_not_called()
        self.assertEqual(len(spoken), 1)

    def test_cancel_shutdown_needs_no_confirmation(self):
        spoken = []
        command = SystemCommand(spoken.append)
        with patch("agent.confirmation_manager.get_confirmation_manager") as get_manager, \
                patch("commands.system_command.subprocess.run") as run:
            run.return_value.returncode = 0
            command.execute("종료 취소")
        get_manager.assert_not_called()
        run.assert_called_once()
        self.assertEqual(run.call_args.args[0][0], "shutdown")


if __name__ == "__main__":
    unittest.main()
