"""Telegram Bot API client — messages, inline keyboards, callback queries."""
from __future__ import annotations

import html
import json
import logging
import os
import urllib.request
import urllib.error

logger = logging.getLogger(__name__)


def _bot_token() -> str:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    if not token:
        raise EnvironmentError("TELEGRAM_BOT_TOKEN is not set.")
    return token


def bot_username() -> str:
    return os.environ.get("TELEGRAM_BOT_USERNAME", "ZealEstateAIBot")


def _api(method: str, payload: dict) -> dict:
    token = _bot_token()
    url = f"https://api.telegram.org/bot{token}/{method}"
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        body = exc.read().decode(errors="ignore")
        logger.error("Telegram API %s failed %s: %s", method, exc.code, body)
        raise


def send_message(chat_id: str | int, text: str, parse_mode: str = "HTML") -> str:
    """Send a plain text message. Returns message_id string."""
    try:
        result = _api("sendMessage", {
            "chat_id": int(chat_id),
            "text": text,
            "parse_mode": parse_mode,
        })
        return str(result.get("result", {}).get("message_id", "sent"))
    except Exception as exc:
        logger.warning("Telegram send SKIPPED (chat=%s): %s | msg: %s", chat_id, exc, text[:100])
        return "skipped"


def send_inline_keyboard(
    chat_id: str | int,
    text: str,
    buttons: list[list[dict]],
    parse_mode: str = "HTML",
) -> str:
    """
    Send a message with an inline keyboard.

    buttons format:
      [ [{"text": "Label", "callback_data": "data"}], ... ]
    Each inner list is a row of buttons.
    """
    try:
        result = _api("sendMessage", {
            "chat_id": int(chat_id),
            "text": text,
            "parse_mode": parse_mode,
            "reply_markup": {"inline_keyboard": buttons},
        })
        return str(result.get("result", {}).get("message_id", "sent"))
    except Exception as exc:
        logger.warning("Telegram keyboard send SKIPPED (chat=%s): %s", chat_id, exc)
        # Fallback: send as plain text
        return send_message(chat_id, text)


def answer_callback(callback_query_id: str, text: str = "") -> None:
    """Dismiss the loading spinner on a pressed inline button."""
    try:
        _api("answerCallbackQuery", {"callback_query_id": callback_query_id, "text": text})
    except Exception as exc:
        logger.warning("answerCallbackQuery failed: %s", exc)


def edit_message_reply_markup(chat_id: str | int, message_id: int, text: str) -> None:
    """Replace keyboard buttons with a plain confirmation text after selection."""
    try:
        _api("editMessageText", {
            "chat_id": int(chat_id),
            "message_id": message_id,
            "text": text,
            "reply_markup": {"inline_keyboard": []},
        })
    except Exception as exc:
        logger.warning("editMessageText failed: %s", exc)


def set_webhook(webhook_url: str) -> dict:
    return _api("setWebhook", {"url": webhook_url, "drop_pending_updates": True})


def parse_update(body: dict) -> tuple[str, str, str, str, str]:
    """
    Parse a Telegram update.
    Returns (chat_id, text, start_payload, callback_query_id, callback_data).
    callback_query_id / callback_data are non-empty only for button presses.
    start_payload is non-empty only for /start <payload> commands.
    """
    # Callback query (button press)
    cq = body.get("callback_query")
    if cq:
        chat_id = str(cq.get("message", {}).get("chat", {}).get("id", ""))
        callback_query_id = str(cq.get("id", ""))
        callback_data = str(cq.get("data", ""))
        return chat_id, "", "", callback_query_id, callback_data

    # Regular message
    msg = body.get("message", {})
    chat_id = str(msg.get("chat", {}).get("id", ""))
    text = msg.get("text", "")
    start_payload = ""
    if text.startswith("/start"):
        parts = text.split(" ", 1)
        if len(parts) > 1:
            start_payload = parts[1].strip()
    return chat_id, text, start_payload, "", ""


# ---------------------------------------------------------------------------
# Structured message builders
# ---------------------------------------------------------------------------

def send_property_type_buttons(chat_id: str | int, lead_id: str, name: str) -> None:
    safe_name = html.escape(name)
    send_inline_keyboard(
        chat_id,
        f"Hi <b>{safe_name}</b> — I'm your ZealEstate assistant.\n\nWhat type of property are you looking for?",
        [
            [{"text": "🏢 Apartment", "callback_data": f"pt:{lead_id}:apartment"},
             {"text": "🏡 House",     "callback_data": f"pt:{lead_id}:house"}],
            [{"text": "🏰 Villa",     "callback_data": f"pt:{lead_id}:villa"},
             {"text": "🏪 Commercial","callback_data": f"pt:{lead_id}:commercial"}],
            [{"text": "🔍 Tell me more…", "callback_data": f"pt:{lead_id}:other"}],
        ],
    )


def send_budget_buttons(chat_id: str | int, lead_id: str) -> None:
    send_inline_keyboard(
        chat_id,
        "Great choice! What's your approximate <b>budget</b>?",
        [
            [{"text": "Under ₹50L",    "callback_data": f"bd:{lead_id}:lt50L"},
             {"text": "₹50L – ₹1Cr",  "callback_data": f"bd:{lead_id}:50-100L"}],
            [{"text": "₹1Cr – ₹2Cr",  "callback_data": f"bd:{lead_id}:1-2Cr"},
             {"text": "₹2Cr+",         "callback_data": f"bd:{lead_id}:gt2Cr"}],
            [{"text": "💬 Type my budget", "callback_data": f"bd:{lead_id}:custom"}],
        ],
    )


def send_availability_question(chat_id: str | int, lead_id: str) -> None:
    send_inline_keyboard(
        chat_id,
        "Almost there! When are you <b>available</b> for a quick call or viewing?",
        [
            [{"text": "📅 This week",    "callback_data": f"av:{lead_id}:thisweek"},
             {"text": "📅 Next week",    "callback_data": f"av:{lead_id}:nextweek"}],
            [{"text": "🗓 Weekends only", "callback_data": f"av:{lead_id}:weekends"},
             {"text": "✍️ Tell me",      "callback_data": f"av:{lead_id}:custom"}],
        ],
    )


def send_slot_buttons(
    chat_id: str | int,
    lead_id: str,
    slots: list[dict],
    refreshed: bool = False,
) -> None:
    """slots: list of {label, start_iso, end_iso, start_ts}"""
    rows = [
        [{"text": s["label"], "callback_data": f"sl:{lead_id}:{s['start_ts']}"}]
        for s in slots[:3]
    ]
    rows.append([{"text": "None of these — show more times",
                  "callback_data": f"rs:{lead_id}"}])
    intro = (
        "Here are updated available times — pick one that works:"
        if refreshed
        else "Here are available times from the calendar. Pick one that works:"
    )
    send_inline_keyboard(chat_id, intro, rows)


def send_booking_confirmation_buttons(chat_id: str | int, lead_id: str, slot_label: str) -> None:
    safe_label = html.escape(slot_label)
    send_inline_keyboard(
        chat_id,
        f"<b>You're confirmed!</b>\n\n{safe_label}\n\nI'll send a reminder before your call.",
        [
            [{"text": "🔄 Reschedule", "callback_data": f"rs:{lead_id}"},
             {"text": "❌ Cancel",      "callback_data": f"cx:{lead_id}"}],
        ],
    )
