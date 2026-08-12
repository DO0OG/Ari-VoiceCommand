"""Google Calendar 서비스 통합 골격."""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any

import requests

from core.resource_manager import ResourceManager

GOOGLE_AUTH_CACHE_FILENAME = "google_token.json"
# Backwards-compatible export used by the Gmail service. This is a filename,
# not an embedded credential.
TOKEN_FILE = GOOGLE_AUTH_CACHE_FILENAME


class GoogleAuthRequired(RuntimeError):
    pass


class GoogleCalendarService:
    def __init__(self, token_path: str | None = None):
        self.token_path = token_path or ResourceManager.get_runtime_path(TOKEN_FILE)

    def get_events(self, calendar_id: str = "primary", days: int = 7, max_results: int = 10) -> list[dict[str, Any]]:
        token = self._access_token()
        now = datetime.utcnow()
        params = {
            "timeMin": now.isoformat() + "Z",
            "timeMax": (now + timedelta(days=int(days))).isoformat() + "Z",
            "singleEvents": "true",
            "orderBy": "startTime",
            "maxResults": int(max_results),
        }
        response = requests.get(
            f"https://www.googleapis.com/calendar/v3/calendars/{calendar_id}/events",
            headers={"Authorization": f"Bearer {token}"},
            params=params,
            timeout=30,
        )
        response.raise_for_status()
        return list(response.json().get("items", []))

    def create_event(self, summary: str, start: str, end: str, calendar_id: str = "primary", description: str = "") -> dict[str, Any]:
        token = self._access_token()
        payload = {
            "summary": summary,
            "description": description,
            "start": {"dateTime": start},
            "end": {"dateTime": end},
        }
        response = requests.post(
            f"https://www.googleapis.com/calendar/v3/calendars/{calendar_id}/events",
            headers={"Authorization": f"Bearer {token}"},
            json=payload,
            timeout=30,
        )
        response.raise_for_status()
        return dict(response.json())

    def _access_token(self) -> str:
        try:
            with open(self.token_path, "r", encoding="utf-8") as handle:
                token_data = json.load(handle)
        except FileNotFoundError as exc:
            raise GoogleAuthRequired("Google 인증 토큰이 없습니다. 설정에서 인증을 먼저 완료해 주세요.") from exc
        token = str(token_data.get("access_token", "") or "")
        if not token:
            raise GoogleAuthRequired("Google 인증 토큰에 access_token이 없습니다.")
        return token


def get_calendar_service() -> GoogleCalendarService:
    return GoogleCalendarService()
