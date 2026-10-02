"""Gmail 서비스 통합 골격."""
from __future__ import annotations

import base64
from email.message import EmailMessage
from typing import Any

import requests

from services import google_auth


class GmailService:
    def send_email(self, to: str, subject: str, body: str) -> dict[str, Any]:
        msg = EmailMessage()
        msg["To"] = to
        msg["Subject"] = subject
        msg.set_content(body)
        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("ascii")
        response = google_auth.request_with_auth(
            requests.post,
            "https://gmail.googleapis.com/gmail/v1/users/me/messages/send",
            json={"raw": raw},
            timeout=30,
        )
        return dict(response.json())

    def read_emails(self, max_results: int = 5, query: str = "in:inbox") -> list[dict[str, Any]]:
        response = google_auth.request_with_auth(
            requests.get,
            "https://gmail.googleapis.com/gmail/v1/users/me/messages",
            params={"maxResults": int(max_results), "q": query},
            timeout=30,
        )
        return list(response.json().get("messages", []))


def get_gmail_service() -> GmailService:
    return GmailService()
