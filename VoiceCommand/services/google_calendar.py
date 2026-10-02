"""Google Calendar 서비스 통합 골격."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import requests

from services import google_auth
from services.google_auth import GoogleAuthRequired

__all__ = ["GoogleAuthRequired", "GoogleCalendarService", "get_calendar_service"]


class GoogleCalendarService:
    def get_events(self, calendar_id: str = "primary", days: int = 7, max_results: int = 10) -> list[dict[str, Any]]:
        now = datetime.now(timezone.utc)
        params = {
            "timeMin": now.isoformat().replace("+00:00", "Z"),
            "timeMax": (now + timedelta(days=int(days))).isoformat().replace("+00:00", "Z"),
            "singleEvents": "true",
            "orderBy": "startTime",
            "maxResults": int(max_results),
        }
        response = google_auth.request_with_auth(
            requests.get,
            f"https://www.googleapis.com/calendar/v3/calendars/{calendar_id}/events",
            params=params,
            timeout=30,
        )
        return list(response.json().get("items", []))

    def create_event(self, summary: str, start: str, end: str, calendar_id: str = "primary", description: str = "") -> dict[str, Any]:
        payload = {
            "summary": summary,
            "description": description,
            "start": {"dateTime": start},
            "end": {"dateTime": end},
        }
        response = google_auth.request_with_auth(
            requests.post,
            f"https://www.googleapis.com/calendar/v3/calendars/{calendar_id}/events",
            json=payload,
            timeout=30,
        )
        return dict(response.json())


def get_calendar_service() -> GoogleCalendarService:
    return GoogleCalendarService()
