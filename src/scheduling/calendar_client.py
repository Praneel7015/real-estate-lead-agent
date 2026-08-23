"""
Google Calendar API wrapper.
Requires GOOGLE_APPLICATION_CREDENTIALS and CALENDAR_ID env vars.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Optional

from src.data.models import Appointment, Lead, TimeSlot


def _get_service():
    try:
        from google.oauth2 import service_account  # type: ignore
        from googleapiclient.discovery import build  # type: ignore

        creds_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
        if not creds_path:
            raise EnvironmentError("GOOGLE_APPLICATION_CREDENTIALS not set.")

        scopes = ["https://www.googleapis.com/auth/calendar"]
        credentials = service_account.Credentials.from_service_account_file(
            creds_path, scopes=scopes
        )
        return build("calendar", "v3", credentials=credentials)
    except ImportError as exc:
        raise RuntimeError(
            "google-api-python-client is required for calendar integration."
        ) from exc


def _calendar_id() -> str:
    return os.environ.get("CALENDAR_ID", "primary")


def _parse_dt(value: str | dict) -> datetime:
    if isinstance(value, dict):
        value = value.get("dateTime") or value.get("date", "")
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def get_free_slots(
    start: datetime,
    end: datetime,
    duration_minutes: int = 30,
) -> list[TimeSlot]:
    """Return free slots of `duration_minutes` within [start, end]."""
    service = _get_service()
    cal_id = _calendar_id()

    body = {
        "timeMin": start.isoformat(),
        "timeMax": end.isoformat(),
        "items": [{"id": cal_id}],
    }
    result = service.freebusy().query(body=body).execute()
    busy_periods = result.get("calendars", {}).get(cal_id, {}).get("busy", [])

    # Convert busy to sorted list of (start, end) tuples
    busy = sorted(
        [(_parse_dt(b["start"]), _parse_dt(b["end"])) for b in busy_periods]
    )

    slots: list[TimeSlot] = []
    cursor = start
    delta = timedelta(minutes=duration_minutes)

    while cursor + delta <= end:
        slot_end = cursor + delta
        overlaps = any(b_start < slot_end and b_end > cursor for b_start, b_end in busy)
        if not overlaps:
            slots.append(TimeSlot(start=cursor, end=slot_end))
        cursor += delta

    return slots


def create_event(lead: Lead, slot: TimeSlot) -> Appointment:
    service = _get_service()
    cal_id = _calendar_id()

    event_body = {
        "summary": f"Property viewing — {lead.name}",
        "description": (
            f"Lead ID: {lead.lead_id}\n"
            f"Phone: {lead.phone}\n"
            f"Budget: {lead.budget}\n"
            f"Preferences: {lead.property_preferences}"
        ),
        "start": {"dateTime": slot.start.isoformat(), "timeZone": "UTC"},
        "end": {"dateTime": slot.end.isoformat(), "timeZone": "UTC"},
    }
    created = service.events().insert(calendarId=cal_id, body=event_body).execute()
    return Appointment(
        event_id=created["id"],
        lead_id=lead.lead_id,
        start=slot.start,
        end=slot.end,
    )


def delete_event(event_id: str) -> None:
    service = _get_service()
    service.events().delete(calendarId=_calendar_id(), eventId=event_id).execute()


def update_event(event_id: str, new_slot: TimeSlot) -> Appointment:
    service = _get_service()
    cal_id = _calendar_id()

    patch_body = {
        "start": {"dateTime": new_slot.start.isoformat(), "timeZone": "UTC"},
        "end": {"dateTime": new_slot.end.isoformat(), "timeZone": "UTC"},
    }
    updated = (
        service.events()
        .patch(calendarId=cal_id, eventId=event_id, body=patch_body)
        .execute()
    )
    return Appointment(
        event_id=updated["id"],
        lead_id="",  # caller fills in
        start=new_slot.start,
        end=new_slot.end,
    )
