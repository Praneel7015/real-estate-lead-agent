"""
Pure deterministic state machine — no LLM, no I/O.
All side effects are returned as action strings; callers execute them.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.data.models import Lead

# ---------------------------------------------------------------------------
# Transition table
# (current_state, event) -> (new_state, [actions])
# ---------------------------------------------------------------------------
_TRANSITIONS: dict[tuple[str, str], tuple[str, list[str]]] = {
    ("NEW", "lead_created"): (
        "CONTACTED",
        ["send_opening_message", "schedule_24h_nudge"],
    ),
    ("CONTACTED", "inbound_message"): (
        "REPLIED",
        ["invoke_conversation_agent"],
    ),
    ("AWAITING_REPLY", "inbound_message"): (
        "REPLIED",
        ["invoke_conversation_agent"],
    ),
    ("AWAITING_REPLY", "timer_24h"): (
        "AWAITING_REPLY",
        ["send_nudge", "schedule_72h_timer"],
    ),
    ("AWAITING_REPLY", "timer_72h"): (
        "STALE",
        ["stop"],
    ),
    ("SCORED", "scored"): (
        "SLOT_OFFERED",
        ["find_slots", "send_slots_message"],
    ),
    ("SLOT_OFFERED", "slot_confirmed"): (
        "BOOKED",
        ["book_slot", "schedule_reminder", "cancel_nudges"],
    ),
    ("BOOKED", "timer_reminder"): (
        "REMINDED",
        ["send_reminder"],
    ),
    ("BOOKED", "cancel_requested"): (
        "CANCELLED",
        ["cancel_calendar", "send_cancellation_ack"],
    ),
    ("BOOKED", "reschedule_requested"): (
        "RESCHEDULE_REQUESTED",
        ["find_slots"],
    ),
    ("SLOT_OFFERED", "reschedule_requested"): (
        "RESCHEDULE_REQUESTED",
        ["find_slots"],
    ),
    ("RESCHEDULE_REQUESTED", "slot_confirmed"): (
        "BOOKED",
        ["book_slot", "schedule_reminder", "cancel_nudges"],
    ),
    ("RESCHEDULE_REQUESTED", "inbound_message"): (
        "RESCHEDULE_REQUESTED",
        ["invoke_conversation_agent"],
    ),
    ("REMINDED", "meeting_done"): (
        "DONE",
        ["alert_salesperson"],
    ),
}


def transition(lead: "Lead", event: str, payload: dict) -> tuple[str, list[str]]:
    """
    Return (new_state, actions_to_take).

    Special cases handled here:
    - REPLIED + is_complete_true event with payload["is_complete"] True/False
    """
    current = lead.state

    # Special: REPLIED + is_complete branch
    if current == "REPLIED" and event == "is_complete_true":
        if payload.get("is_complete"):
            return "SCORED", ["invoke_scoring"]
        else:
            return "AWAITING_REPLY", ["invoke_conversation_agent"]

    key = (current, event)
    if key in _TRANSITIONS:
        new_state, actions = _TRANSITIONS[key]
        return new_state, list(actions)

    # No matching transition — stay put
    return current, []
