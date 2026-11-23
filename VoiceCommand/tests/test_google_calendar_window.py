import unittest
from datetime import datetime, timedelta
from unittest.mock import Mock, patch

from services.google_calendar import GoogleCalendarService


class GoogleCalendarWindowTests(unittest.TestCase):
    def test_get_events_between_sends_window_as_time_min_and_max(self):
        start = datetime(2026, 11, 24, 0, 0)
        end = start + timedelta(days=1)
        response = Mock()
        response.json.return_value = {"items": [{"summary": "팀 회의"}]}

        with patch("services.google_auth.request_with_auth", return_value=response) as request:
            events = GoogleCalendarService().get_events_between(start, end)

        self.assertEqual(events, [{"summary": "팀 회의"}])
        args, kwargs = request.call_args
        self.assertTrue(args[1].endswith("/calendars/primary/events"))
        self.assertEqual(kwargs["params"]["timeMin"], start.astimezone().isoformat())
        self.assertEqual(kwargs["params"]["timeMax"], end.astimezone().isoformat())


if __name__ == "__main__":
    unittest.main()
