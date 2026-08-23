"""
Unit tests for the Google Calendar client (all API calls mocked).
"""
from __future__ import annotations

import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock
from src.data.models import Lead, Appointment, TimeSlot


def _utc(year=2026, month=8, day=25, hour=10, minute=0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=timezone.utc)


def _make_lead() -> Lead:
    return Lead(
        lead_id="lead-42",
        phone="+19999999999",
        name="Jane Smith",
        budget="$400k",
        property_preferences="3-bed apartment",
        availability="Saturday morning",
    )


def _mock_service(busy_periods=None):
    """Build a mock googleapiclient service."""
    busy_periods = busy_periods or []

    freebusy_result = {
        "calendars": {
            "primary": {
                "busy": busy_periods
            }
        }
    }
    mock_freebusy = MagicMock()
    mock_freebusy.query.return_value.execute.return_value = freebusy_result

    mock_service = MagicMock()
    mock_service.freebusy.return_value = mock_freebusy
    return mock_service


class TestGetFreeSlots:
    def test_returns_slots_when_calendar_is_empty(self):
        from src.scheduling.calendar_client import get_free_slots

        start = _utc(hour=9)
        end = _utc(hour=11)

        with patch("src.scheduling.calendar_client._get_service", return_value=_mock_service()):
            with patch.dict("os.environ", {"CALENDAR_ID": "primary"}):
                slots = get_free_slots(start, end, duration_minutes=30)

        assert len(slots) == 4  # 9:00, 9:30, 10:00, 10:30

    def test_skips_busy_periods(self):
        from src.scheduling.calendar_client import get_free_slots

        start = _utc(hour=9)
        end = _utc(hour=11)
        busy = [
            {"start": _utc(hour=9).isoformat(), "end": _utc(hour=10).isoformat()}
        ]

        with patch("src.scheduling.calendar_client._get_service", return_value=_mock_service(busy)):
            with patch.dict("os.environ", {"CALENDAR_ID": "primary"}):
                slots = get_free_slots(start, end, duration_minutes=30)

        # 9:00 and 9:30 are busy; 10:00 and 10:30 are free
        assert len(slots) == 2
        assert all(s.start >= _utc(hour=10) for s in slots)

    def test_no_slots_when_fully_busy(self):
        from src.scheduling.calendar_client import get_free_slots

        start = _utc(hour=9)
        end = _utc(hour=11)
        busy = [
            {"start": _utc(hour=9).isoformat(), "end": _utc(hour=11).isoformat()}
        ]

        with patch("src.scheduling.calendar_client._get_service", return_value=_mock_service(busy)):
            with patch.dict("os.environ", {"CALENDAR_ID": "primary"}):
                slots = get_free_slots(start, end, duration_minutes=30)

        assert slots == []

    def test_returns_timeslot_objects(self):
        from src.scheduling.calendar_client import get_free_slots

        start = _utc(hour=14)
        end = _utc(hour=15)

        with patch("src.scheduling.calendar_client._get_service", return_value=_mock_service()):
            with patch.dict("os.environ", {"CALENDAR_ID": "primary"}):
                slots = get_free_slots(start, end, duration_minutes=30)

        assert all(isinstance(s, TimeSlot) for s in slots)
        for slot in slots:
            assert (slot.end - slot.start) == timedelta(minutes=30)


class TestCreateEvent:
    def test_create_event_returns_appointment(self):
        from src.scheduling.calendar_client import create_event

        lead = _make_lead()
        slot = TimeSlot(start=_utc(hour=10), end=_utc(hour=10, minute=30))

        created_event = {
            "id": "event-abc-123",
            "start": {"dateTime": slot.start.isoformat()},
            "end": {"dateTime": slot.end.isoformat()},
        }

        mock_service = MagicMock()
        mock_service.events.return_value.insert.return_value.execute.return_value = created_event

        with patch("src.scheduling.calendar_client._get_service", return_value=mock_service):
            with patch.dict("os.environ", {"CALENDAR_ID": "primary"}):
                appt = create_event(lead, slot)

        assert isinstance(appt, Appointment)
        assert appt.event_id == "event-abc-123"
        assert appt.lead_id == lead.lead_id
        assert appt.start == slot.start
        assert appt.end == slot.end

    def test_create_event_calls_correct_calendar(self):
        from src.scheduling.calendar_client import create_event

        lead = _make_lead()
        slot = TimeSlot(start=_utc(hour=10), end=_utc(hour=10, minute=30))

        mock_service = MagicMock()
        mock_service.events.return_value.insert.return_value.execute.return_value = {
            "id": "evt-1",
            "start": {"dateTime": slot.start.isoformat()},
            "end": {"dateTime": slot.end.isoformat()},
        }

        with patch("src.scheduling.calendar_client._get_service", return_value=mock_service):
            with patch.dict("os.environ", {"CALENDAR_ID": "work-calendar"}):
                create_event(lead, slot)

        call_kwargs = mock_service.events.return_value.insert.call_args[1]
        assert call_kwargs.get("calendarId") == "work-calendar"
