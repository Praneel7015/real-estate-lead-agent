"""
Scheduling agent — matches lead availability to calendar slots and
generates WhatsApp scheduling messages via Gemini.
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timedelta, timezone
from typing import Optional

from src.data.models import Appointment, Lead, TimeSlot
from src.scheduling import calendar_client

_SCHEDULING_PROMPT = """You help match a lead's stated availability to real open calendar slots,
and phrase scheduling messages for WhatsApp.

TASK 1 — Match availability to slots
Given: lead's stated availability in their own words, and a list of real free slots.
Select up to 3 slots that best match. If nothing matches well, select 3 earliest instead.
Never claim a slot matches when it doesn't.

TASK 2 — Phrasing
Write a short WhatsApp message (2-3 sentences max) offering the matched slots naturally.

Also handle: CONFIRMATION, RESCHEDULE, CANCELLATION ACK, 24h REMINDER messages.

OUTPUT FORMAT — ONLY this JSON:
{
  "message_text": "<WhatsApp message>",
  "offered_slots": [{"start": "<ISO>", "end": "<ISO>"}]
}"""


def _get_gemini_model():
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise EnvironmentError("GEMINI_API_KEY environment variable is not set.")
    import google.generativeai as genai  # type: ignore

    genai.configure(api_key=api_key)
    return genai.GenerativeModel("gemini-2.5-flash")


def _strip_fences(text: str) -> str:
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    return text.strip()


def _slots_to_text(slots: list[TimeSlot]) -> str:
    lines = []
    for s in slots:
        lines.append(f"  - {s.start.strftime('%A %d %b %Y %H:%M')} – {s.end.strftime('%H:%M')} UTC")
    return "\n".join(lines)


def find_slots(preferred_window: Optional[str] = None) -> list[TimeSlot]:
    """Return up to 6 open slots within the next 7 days (top 3 shown to lead)."""
    now = datetime.now(tz=timezone.utc)
    end = now + timedelta(days=7)
    all_slots = calendar_client.get_free_slots(now, end, duration_minutes=30)
    return all_slots[:6]  # Pass top 6 to Gemini for selection


def book_slot(lead_id: str, slot: TimeSlot, lead: Lead) -> Appointment:
    return calendar_client.create_event(lead, slot)


def reschedule(lead_id: str, new_slot: TimeSlot, event_id: str) -> Appointment:
    appt = calendar_client.update_event(event_id, new_slot)
    appt.lead_id = lead_id
    return appt


def cancel(lead_id: str, event_id: str) -> None:
    calendar_client.delete_event(event_id)


def build_slot_offer_message(lead: Lead, slots: list[TimeSlot]) -> str:
    model = _get_gemini_model()
    slots_text = _slots_to_text(slots[:3])
    prompt = (
        f"{_SCHEDULING_PROMPT}\n\n"
        f"TASK: Offer these slots to {lead.name} naturally.\n"
        f"Lead's stated availability: {lead.availability or 'not specified'}\n"
        f"Available slots:\n{slots_text}\n\n"
        "Return only the JSON."
    )
    response = model.generate_content(prompt)
    data = json.loads(_strip_fences(response.text))
    return data.get("message_text", "Hi! Here are some available times for a quick call.")


def build_confirmation_message(lead: Lead, appt: Appointment) -> str:
    start_str = appt.start.strftime("%A %d %b at %H:%M UTC")
    return (
        f"Great, {lead.name}! You're confirmed for {start_str}. "
        "I'll send you a reminder the day before. Looking forward to it!"
    )


def build_reminder_message(lead: Lead, appt: Appointment) -> str:
    start_str = appt.start.strftime("%A %d %b at %H:%M UTC")
    return (
        f"Hi {lead.name}, just a friendly reminder about your appointment tomorrow "
        f"at {start_str}. See you then!"
    )


def build_cancellation_message(lead: Lead) -> str:
    return (
        f"No problem, {lead.name}! Your appointment has been cancelled. "
        "Feel free to reach out whenever you'd like to reschedule."
    )
