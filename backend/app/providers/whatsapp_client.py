"""
WhatsApp transport adapters.

The flow engine is transport-agnostic. This module is the only place that
knows about Meta's Cloud API, so a switch to Gupshup/Twilio/AiSensy means
writing one new class here.
"""

from __future__ import annotations

import hashlib
import hmac
import os
from typing import Any, Protocol

import requests

GRAPH_VERSION = os.getenv("WHATSAPP_GRAPH_VERSION", "v21.0")


class WhatsAppClient(Protocol):
    def send_text(self, to: str, body: str) -> dict: ...
    def download_media(self, media_id: str) -> str | None: ...


class ConsoleWhatsAppClient:
    """
    Demo/offline adapter. Records outbound messages instead of sending them
    so the whole funnel is demonstrable without a Meta Business account.
    """

    def __init__(self) -> None:
        self.sent: list[dict] = []

    def send_text(self, to: str, body: str) -> dict:
        record = {"to": to, "body": body, "channel": "console"}
        self.sent.append(record)
        return {"status": "logged", **record}

    def download_media(self, media_id: str) -> str | None:
        return f"console://media/{media_id}"


class MetaCloudWhatsAppClient:
    """Meta WhatsApp Cloud API adapter."""

    def __init__(
        self,
        access_token: str | None = None,
        phone_number_id: str | None = None,
        timeout: int = 15,
    ) -> None:
        self.access_token = access_token or os.getenv("WHATSAPP_ACCESS_TOKEN", "")
        self.phone_number_id = phone_number_id or os.getenv(
            "WHATSAPP_PHONE_NUMBER_ID", ""
        )
        self.timeout = timeout

    @property
    def configured(self) -> bool:
        return bool(self.access_token and self.phone_number_id)

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
        }

    def send_text(self, to: str, body: str) -> dict:
        if not self.configured:
            return {"status": "not_configured",
                    "detail": "WHATSAPP_ACCESS_TOKEN / PHONE_NUMBER_ID missing"}

        url = (
            f"https://graph.facebook.com/{GRAPH_VERSION}/"
            f"{self.phone_number_id}/messages"
        )
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to,
            "type": "text",
            # Our own message bodies, never user-supplied -> no preview risk.
            "text": {"preview_url": False, "body": body},
        }
        try:
            response = requests.post(
                url, json=payload, headers=self._headers(), timeout=self.timeout
            )
            response.raise_for_status()
            return {"status": "sent", "response": response.json()}
        except requests.RequestException as exc:
            return {"status": "failed", "error": str(exc)}

    def download_media(self, media_id: str) -> str | None:
        """Resolve a media id to a temporary download URL."""
        if not self.configured:
            return None
        try:
            meta = requests.get(
                f"https://graph.facebook.com/{GRAPH_VERSION}/{media_id}",
                headers={"Authorization": f"Bearer {self.access_token}"},
                timeout=self.timeout,
            )
            meta.raise_for_status()
            return meta.json().get("url")
        except requests.RequestException:
            return None


def verify_signature(app_secret: str, raw_body: bytes, header: str | None) -> bool:
    """
    Validate X-Hub-Signature-256. Without this anyone who learns the URL can
    inject fake leads and fake qualification answers.
    """
    if not app_secret:
        return True  # unset in dev; enforce in production via env
    if not header or not header.startswith("sha256="):
        return False
    expected = hmac.new(
        app_secret.encode(), raw_body, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, header.split("=", 1)[1])


def parse_webhook(payload: dict[str, Any]) -> list[dict]:
    """
    Flatten a Meta Cloud API webhook into simple message dicts.

    Real payloads nest as entry[].changes[].value.messages[]. The previous
    flat schema would never have bound against a live webhook.
    """
    messages: list[dict] = []

    for entry in payload.get("entry", []) or []:
        for change in entry.get("changes", []) or []:
            value = change.get("value", {}) or {}

            # Delivery/read receipts: useful for SLA, not for the flow.
            for status in value.get("statuses", []) or []:
                messages.append({
                    "kind": "status",
                    "message_id": status.get("id"),
                    "phone": status.get("recipient_id"),
                    "status": status.get("status"),
                    "timestamp": status.get("timestamp"),
                })

            for message in value.get("messages", []) or []:
                record = {
                    "kind": "message",
                    "message_id": message.get("id"),
                    "phone": message.get("from"),
                    "timestamp": message.get("timestamp"),
                    "type": message.get("type"),
                    "text": None,
                    "media_id": None,
                    "media_type": None,
                }

                mtype = message.get("type")
                if mtype == "text":
                    record["text"] = (message.get("text") or {}).get("body")
                elif mtype in {"image", "document"}:
                    media = message.get(mtype) or {}
                    record["media_id"] = media.get("id")
                    record["media_type"] = media.get("mime_type")
                    record["text"] = media.get("caption")
                elif mtype == "interactive":
                    interactive = message.get("interactive") or {}
                    reply = (
                        interactive.get("button_reply")
                        or interactive.get("list_reply")
                        or {}
                    )
                    record["text"] = reply.get("id") or reply.get("title")
                elif mtype == "button":
                    record["text"] = (message.get("button") or {}).get("text")
                elif mtype == "location":
                    location = message.get("location") or {}
                    record["latitude"] = location.get("latitude")
                    record["longitude"] = location.get("longitude")
                    record["text"] = location.get("address")

                messages.append(record)

    return messages


_client: WhatsAppClient | None = None


def get_client() -> WhatsAppClient:
    global _client
    if _client is None:
        meta = MetaCloudWhatsAppClient()
        _client = meta if meta.configured else ConsoleWhatsAppClient()
    return _client


def set_client(client: WhatsAppClient) -> None:
    global _client
    _client = client