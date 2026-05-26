"""Gmail 서비스 통합 골격."""
from __future__ import annotations

import base64
import json
from email.message import EmailMessage
from typing import Any

import requests

from core.resource_manager import ResourceManager
from services.google_calendar import GoogleAuthRequired, TOKEN_FILE


class GmailService:
    def __init__(self, token_path: str | None = None):
        self.token_path = token_path or ResourceManager.get_runtime_path(TOKEN_FILE)

    def send_email(self, to: str, subject: str, body: str) -> dict[str, Any]:
        token = self._access_token()
        msg = EmailMessage()
        msg["To"] = to
        msg["Subject"] = subject
        msg.set_content(body)
        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("ascii")
        response = requests.post(
            "https://gmail.googleapis.com/gmail/v1/users/me/messages/send",
            headers={"Authorization": f"Bearer {token}"},
            json={"raw": raw},
            timeout=30,
        )
        response.raise_for_status()
        return dict(response.json())

    def read_emails(self, max_results: int = 5, query: str = "in:inbox") -> list[dict[str, Any]]:
        token = self._access_token()
        response = requests.get(
            "https://gmail.googleapis.com/gmail/v1/users/me/messages",
            headers={"Authorization": f"Bearer {token}"},
            params={"maxResults": int(max_results), "q": query},
            timeout=30,
        )
        response.raise_for_status()
        return list(response.json().get("messages", []))

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


def get_gmail_service() -> GmailService:
    return GmailService()
