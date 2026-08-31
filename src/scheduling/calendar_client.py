"""
Google Calendar client using Application Default Credentials (ADC).
On Cloud Run the attached service account is used automatically — no key file needed.

SETUP (one-time):
  1. Enable Calendar API:
     gcloud services enable calendar-json.googleapis.com --project=real-estate-agent-hack
  2. Share your Google Calendar with the service account:
     real-estate-agent-sa@real-estate-agent-hack.iam.gserviceaccount.com
     (give it "Make changes to events" permission)
  3. Copy the Calendar ID from Google Calendar → Settings → Calendar Settings
  4. Add it as GitHub secret CALENDAR_ID and redeploy
"""
from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime, timedelta, timezone

from src.data.models import Appointment, Lead, TimeSlot

logger = logging.getLogger(__name__)

# Business hours fallback (used when Calendar API is unavailable)
_SLOT_HOUR_START = 9
_SLOT_HOUR_END = 18
_SLOT_DURATION = 30


def _get_service():
    """Build a Google Calendar API service using ADC."""
    try:
        from google.auth import default  # type: ignore
        from googleapiclient.discovery import build  # type: ignore

        credentials, _ = default(scopes=["https://www.googleapis.com/auth/calendar"])
        return build("calendar", "v3", credentials=credentials, cache_discovery=False)
    except ImportError as exc:
        raise RuntimeError("google-api-python-client is required.") from exc
    except Exception as exc:
        raise RuntimeError(f"Calendar service unavailable: {exc}") from exc


def _calendar_id() -> str:
    cal_id = os.environ.get("CALENDAR_ID", "")
    if not cal_id:
        raise EnvironmentError(
            "CALENDAR_ID env var not set. "
            "Share your Google Calendar with real-estate-agent-sa@real-estate-agent-hack.iam.gserviceaccount.com, "
            "copy the Calendar ID from Calendar Settings, and add it as CALENDAR_ID in GitHub secrets."
        )
    return cal_id


def _parse_dt(value: str | dict) -> datetime:
    if isinstance(value, dict):
        value = value.get("dateTime") or value.get("date", "")
    dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _fallback_slots(start: datetime, end: datetime, duration_minutes: int) -> list[TimeSlot]:
    """Generate business-hour slots without hitting the Calendar API."""
    delta = timedelta(minutes=duration_minutes)
    slots: list[TimeSlot] = []
    cursor = start.replace(minute=0, second=0, microsecond=0)
    while cursor + delta <= end and len(slots) < 12:
        if _SLOT_HOUR_START <= cursor.hour < _SLOT_HOUR_END:
            slots.append(TimeSlot(start=cursor, end=cursor + delta))
        cursor += delta
    return slots


def get_free_slots(
    start: datetime,
    end: datetime,
    duration_minutes: int = _SLOT_DURATION,
) -> list[TimeSlot]:
    """Return free 30-min slots from Google Calendar. Falls back to business hours if unconfigured."""
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    if end.tzinfo is None:
        end = end.replace(tzinfo=timezone.utc)

    try:
        service = _get_service()
        cal_id = _calendar_id()
    except EnvironmentError as exc:
        logger.warning("Calendar not configured, using fallback slots: %s", exc)
        return _fallback_slots(start, end, duration_minutes)
    except Exception as exc:
        logger.warning("Calendar API unavailable, using fallback slots: %s", exc)
        return _fallback_slots(start, end, duration_minutes)

    try:
        body = {
            "timeMin": start.isoformat(),
            "timeMax": end.isoformat(),
            "items": [{"id": cal_id}],
        }
        result = service.freebusy().query(body=body).execute()
        busy_periods = result.get("calendars", {}).get(cal_id, {}).get("busy", [])
        busy = sorted([(_parse_dt(b["start"]), _parse_dt(b["end"])) for b in busy_periods])

        delta = timedelta(minutes=duration_minutes)
        slots: list[TimeSlot] = []
        cursor = start.replace(minute=0, second=0, microsecond=0)

        while cursor + delta <= end and len(slots) < 12:
            if _SLOT_HOUR_START <= cursor.hour < _SLOT_HOUR_END:
                slot_end = cursor + delta
                overlaps = any(b_s < slot_end and b_e > cursor for b_s, b_e in busy)
                if not overlaps:
                    slots.append(TimeSlot(start=cursor, end=slot_end))
            cursor += delta

        logger.info("Found %d free slots from Google Calendar", len(slots))
        return slots

    except Exception as exc:
        logger.warning("freebusy query failed, using fallback: %s", exc)
        return _fallback_slots(start, end, duration_minutes)


def create_event(lead: Lead, slot: TimeSlot) -> Appointment:
    """Create a Google Calendar event. Falls back to Firestore-only if unconfigured."""
    event_id = str(uuid.uuid4())

    try:
        service = _get_service()
        cal_id = _calendar_id()

        event_body = {
            "summary": f"Property Viewing — {lead.name}",
            "description": (
                f"Lead ID: {lead.lead_id}\n"
                f"Phone: {lead.phone}\n"
                f"Budget: {lead.budget or 'N/A'}\n"
                f"Preferences: {lead.property_preferences or 'N/A'}\n"
                f"Availability: {lead.availability or 'N/A'}"
            ),
            "start": {"dateTime": slot.start.isoformat(), "timeZone": "UTC"},
            "end":   {"dateTime": slot.end.isoformat(),   "timeZone": "UTC"},
        }
        created = service.events().insert(calendarId=cal_id, body=event_body).execute()
        event_id = created["id"]
        logger.info("Google Calendar event created: %s", event_id)

    except EnvironmentError:
        logger.info("CALENDAR_ID not set — saving booking to Firestore only.")
    except Exception as exc:
        logger.warning("Calendar event creation failed, saving to Firestore: %s", exc)

    # Always persist to Firestore regardless of Calendar success
    try:
        from src.data.firestore_client import _get_client
        _get_client().collection("appointments").document(event_id).set({
            "event_id": event_id,
            "lead_id": lead.lead_id,
            "lead_name": lead.name,
            "lead_phone": lead.phone,
            "budget": lead.budget,
            "property_preferences": lead.property_preferences,
            "start": slot.start.isoformat(),
            "end": slot.end.isoformat(),
            "created_at": datetime.now(tz=timezone.utc).isoformat(),
        })
    except Exception as exc:
        logger.warning("Firestore appointment save failed: %s", exc)

    return Appointment(event_id=event_id, lead_id=lead.lead_id, start=slot.start, end=slot.end)


def delete_event(event_id: str) -> None:
    try:
        service = _get_service()
        service.events().delete(calendarId=_calendar_id(), eventId=event_id).execute()
        logger.info("Google Calendar event deleted: %s", event_id)
    except Exception as exc:
        logger.warning("Calendar delete failed: %s", exc)
    try:
        from src.data.firestore_client import _get_client
        _get_client().collection("appointments").document(event_id).delete()
    except Exception as exc:
        logger.warning("Firestore appointment delete failed: %s", exc)


def update_event(event_id: str, new_slot: TimeSlot) -> Appointment:
    try:
        service = _get_service()
        patch = {
            "start": {"dateTime": new_slot.start.isoformat(), "timeZone": "UTC"},
            "end":   {"dateTime": new_slot.end.isoformat(),   "timeZone": "UTC"},
        }
        service.events().patch(calendarId=_calendar_id(), eventId=event_id, body=patch).execute()
    except Exception as exc:
        logger.warning("Calendar update failed: %s", exc)
    try:
        from src.data.firestore_client import _get_client
        _get_client().collection("appointments").document(event_id).update({
            "start": new_slot.start.isoformat(),
            "end": new_slot.end.isoformat(),
        })
    except Exception as exc:
        logger.warning("Firestore appointment update failed: %s", exc)
    return Appointment(event_id=event_id, lead_id="", start=new_slot.start, end=new_slot.end)
