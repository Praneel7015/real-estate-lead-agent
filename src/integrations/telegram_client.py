"""Telegram Bot API client — send messages and parse inbound webhook updates."""
from __future__ import annotations

import json
import logging
import os
import urllib.request

logger = logging.getLogger(__name__)


def _bot_token() -> str:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    if not token:
        raise EnvironmentError("TELEGRAM_BOT_TOKEN is not set.")
    return token


def bot_name() -> str:
    """Return the bot username (without @) from env, used for deep links."""
    return os.environ.get("TELEGRAM_BOT_USERNAME", "ZealEstateAIBot")


def _api(method: str, payload: dict) -> dict:
    token = _bot_token()
    url = f"https://api.telegram.org/bot{token}/{method}"
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read())


def send_message(chat_id: str | int, text: str) -> str:
    """Send a text message to a Telegram chat. Returns message_id as string."""
    try:
        result = _api("sendMessage", {"chat_id": int(chat_id), "text": text})
        msg_id = str(result.get("result", {}).get("message_id", "sent"))
        logger.info("Telegram message sent to chat_id=%s msg_id=%s", chat_id, msg_id)
        return msg_id
    except Exception as exc:
        logger.warning(
            "Telegram send SKIPPED (chat_id=%s): %s — message: %s",
            chat_id, exc, text[:120],
        )
        return "skipped"


def set_webhook(webhook_url: str) -> dict:
    """Register the Cloud Run webhook URL with Telegram."""
    return _api("setWebhook", {"url": webhook_url, "drop_pending_updates": True})


def parse_update(body: dict) -> tuple[str, str, str]:
    """
    Parse a Telegram update payload.
    Returns (chat_id, text, start_payload).
    start_payload is non-empty only for /start <lead_id> deep-link commands.
    """
    msg = body.get("message", {})
    chat_id = str(msg.get("chat", {}).get("id", ""))
    text = msg.get("text", "")
    start_payload = ""
    if text.startswith("/start"):
        parts = text.split(" ", 1)
        if len(parts) > 1:
            start_payload = parts[1].strip()
    return chat_id, text, start_payload
