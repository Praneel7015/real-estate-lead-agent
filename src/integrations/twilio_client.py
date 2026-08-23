"""
Twilio WhatsApp client — send and parse inbound messages.
"""
from __future__ import annotations

import os


def _get_client():
    account_sid = os.environ.get("TWILIO_ACCOUNT_SID")
    auth_token = os.environ.get("TWILIO_AUTH_TOKEN")
    if not account_sid or not auth_token:
        raise EnvironmentError(
            "TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN must be set."
        )
    from twilio.rest import Client  # type: ignore

    return Client(account_sid, auth_token)


def _from_number() -> str:
    number = os.environ.get("TWILIO_WHATSAPP_FROM", "whatsapp:+14155238886")
    return number


def send_whatsapp(to: str, body: str) -> str:
    """Send a WhatsApp message. Returns the Twilio message SID."""
    client = _get_client()
    to_number = to if to.startswith("whatsapp:") else f"whatsapp:{to}"
    message = client.messages.create(
        from_=_from_number(),
        to=to_number,
        body=body,
    )
    return message.sid


def parse_inbound_webhook(form_data: dict) -> tuple[str, str]:
    """
    Parse a Twilio inbound WhatsApp webhook form post.
    Returns (from_number, body_text).
    """
    from_number = form_data.get("From", "")
    body = form_data.get("Body", "")
    # Strip whatsapp: prefix for storage
    from_clean = from_number.replace("whatsapp:", "")
    return from_clean, body
