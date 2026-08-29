"""
Calendar backend — generates realistic slots and persists bookings in Firestore.
No Google Calendar API credentials required. Drop-in replacement for demo/hackathon use.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from src.data.models import Appointment, Lead, TimeSlot

# Business hours window used when generating slots
_SLOT_HOUR_START = 9   # 9 AM UTC
_SLOT_HOUR_END = 18    # 6 PM UTC
_SLOT_DURATION = 30    # minutes


def _booked_slots() -> list[tuple[datetime, datetime]]:
    """Load already-booked slot windows from Firestore."""
    try:
        from src.data.firestore_client import _get_client
        db = _get_client()
        docs = db.collection("appointments").stream()
        result = []
        for doc in docs:
            d = doc.to_dict()
            start = datetime.fromisoformat(d["start"])
            end = datetime.fromisoformat(d["end"])
            if start.tzinfo is None:
                start = start.replace(tzinfo=timezone.utc)
            if end.tzinfo is None:
                end = end.replace(tzinfo=timezone.utc)
            result.append((start, end))
        return result
    except Exception:
        return []


def get_free_slots(
    start: datetime,
    end: datetime,
    duration_minutes: int = _SLOT_DURATION,
) -> list[TimeSlot]:
    """Return free 30-min slots within business hours over the next 7 days."""
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    if end.tzinfo is None:
        end = end.replace(tzinfo=timezone.utc)

    booked = _booked_slots()
    delta = timedelta(minutes=duration_minutes)
    slots: list[TimeSlot] = []
    cursor = start.replace(minute=0, second=0, microsecond=0)

    while cursor + delta <= end and len(slots) < 12:
        # Only offer slots within business hours
        if _SLOT_HOUR_START <= cursor.hour < _SLOT_HOUR_END:
            slot_end = cursor + delta
            overlaps = any(
                b_start < slot_end and b_end > cursor
                for b_start, b_end in booked
            )
            if not overlaps:
                slots.append(TimeSlot(start=cursor, end=slot_end))
        cursor += delta

    return slots


def create_event(lead: Lead, slot: TimeSlot) -> Appointment:
    """Persist a booking in Firestore and return an Appointment."""
    event_id = str(uuid.uuid4())
    appt = Appointment(
        event_id=event_id,
        lead_id=lead.lead_id,
        start=slot.start,
        end=slot.end,
    )
    try:
        from src.data.firestore_client import _get_client
        db = _get_client()
        db.collection("appointments").document(event_id).set({
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
        import logging
        logging.getLogger(__name__).warning("Could not persist appointment: %s", exc)
    return appt


def delete_event(event_id: str) -> None:
    """Remove a booking from Firestore."""
    try:
        from src.data.firestore_client import _get_client
        _get_client().collection("appointments").document(event_id).delete()
    except Exception as exc:
        import logging
        logging.getLogger(__name__).warning("Could not delete appointment %s: %s", event_id, exc)


def update_event(event_id: str, new_slot: TimeSlot) -> Appointment:
    """Reschedule a booking in Firestore."""
    try:
        from src.data.firestore_client import _get_client
        _get_client().collection("appointments").document(event_id).update({
            "start": new_slot.start.isoformat(),
            "end": new_slot.end.isoformat(),
        })
    except Exception as exc:
        import logging
        logging.getLogger(__name__).warning("Could not update appointment %s: %s", event_id, exc)
    return Appointment(event_id=event_id, lead_id="", start=new_slot.start, end=new_slot.end)
