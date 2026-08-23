"""
Unit tests for the deterministic state machine.
Tests every transition in the table and verifies invalid transitions stay put.
"""
from __future__ import annotations

import pytest
from src.data.models import Lead
from src.coordinator.state_machine import transition


def _lead(state: str) -> Lead:
    return Lead(lead_id="test-1", phone="+10000000000", name="Test Lead", state=state)


class TestHappyPathTransitions:
    def test_new_lead_created(self):
        lead = _lead("NEW")
        new_state, actions = transition(lead, "lead_created", {})
        assert new_state == "CONTACTED"
        assert "send_opening_message" in actions
        assert "schedule_24h_nudge" in actions

    def test_contacted_inbound_message(self):
        lead = _lead("CONTACTED")
        new_state, actions = transition(lead, "inbound_message", {})
        assert new_state == "REPLIED"
        assert "invoke_conversation_agent" in actions

    def test_awaiting_reply_inbound_message(self):
        lead = _lead("AWAITING_REPLY")
        new_state, actions = transition(lead, "inbound_message", {})
        assert new_state == "REPLIED"
        assert "invoke_conversation_agent" in actions

    def test_awaiting_reply_timer_24h(self):
        lead = _lead("AWAITING_REPLY")
        new_state, actions = transition(lead, "timer_24h", {})
        assert new_state == "AWAITING_REPLY"
        assert "send_nudge" in actions
        assert "schedule_72h_timer" in actions

    def test_awaiting_reply_timer_72h(self):
        lead = _lead("AWAITING_REPLY")
        new_state, actions = transition(lead, "timer_72h", {})
        assert new_state == "STALE"
        assert "stop" in actions

    def test_replied_is_complete_false(self):
        lead = _lead("REPLIED")
        new_state, actions = transition(lead, "is_complete_true", {"is_complete": False})
        assert new_state == "AWAITING_REPLY"
        assert "invoke_conversation_agent" in actions

    def test_replied_is_complete_true(self):
        lead = _lead("REPLIED")
        new_state, actions = transition(lead, "is_complete_true", {"is_complete": True})
        assert new_state == "SCORED"
        assert "invoke_scoring" in actions

    def test_scored_to_slot_offered(self):
        lead = _lead("SCORED")
        new_state, actions = transition(lead, "scored", {})
        assert new_state == "SLOT_OFFERED"
        assert "find_slots" in actions
        assert "send_slots_message" in actions

    def test_slot_offered_confirmed(self):
        lead = _lead("SLOT_OFFERED")
        new_state, actions = transition(lead, "slot_confirmed", {})
        assert new_state == "BOOKED"
        assert "book_slot" in actions
        assert "schedule_reminder" in actions
        assert "cancel_nudges" in actions

    def test_booked_timer_reminder(self):
        lead = _lead("BOOKED")
        new_state, actions = transition(lead, "timer_reminder", {})
        assert new_state == "REMINDED"
        assert "send_reminder" in actions

    def test_booked_cancel_requested(self):
        lead = _lead("BOOKED")
        new_state, actions = transition(lead, "cancel_requested", {})
        assert new_state == "CANCELLED"
        assert "cancel_calendar" in actions
        assert "send_cancellation_ack" in actions

    def test_booked_reschedule_requested(self):
        lead = _lead("BOOKED")
        new_state, actions = transition(lead, "reschedule_requested", {})
        assert new_state == "SLOT_OFFERED"
        assert "find_slots" in actions
        assert "send_reschedule_slots" in actions

    def test_slot_offered_reschedule_requested(self):
        lead = _lead("SLOT_OFFERED")
        new_state, actions = transition(lead, "reschedule_requested", {})
        assert new_state == "SLOT_OFFERED"
        assert "find_slots" in actions

    def test_reminded_meeting_done(self):
        lead = _lead("REMINDED")
        new_state, actions = transition(lead, "meeting_done", {})
        assert new_state == "DONE"
        assert "alert_salesperson" in actions


class TestInvalidTransitions:
    def test_done_ignores_all_events(self):
        lead = _lead("DONE")
        for event in ["lead_created", "inbound_message", "timer_24h", "scored"]:
            new_state, actions = transition(lead, event, {})
            assert new_state == "DONE", f"DONE state changed on event {event}"
            assert actions == []

    def test_stale_ignores_events(self):
        lead = _lead("STALE")
        new_state, actions = transition(lead, "inbound_message", {})
        assert new_state == "STALE"
        assert actions == []

    def test_new_ignores_inbound_message(self):
        lead = _lead("NEW")
        new_state, actions = transition(lead, "inbound_message", {})
        # NEW has no inbound_message rule — unchanged
        assert new_state == "NEW"
        assert actions == []

    def test_cancelled_ignores_events(self):
        lead = _lead("CANCELLED")
        new_state, actions = transition(lead, "slot_confirmed", {})
        assert new_state == "CANCELLED"
        assert actions == []

    def test_unknown_event_ignored(self):
        lead = _lead("AWAITING_REPLY")
        new_state, actions = transition(lead, "nonexistent_event", {})
        assert new_state == "AWAITING_REPLY"
        assert actions == []
