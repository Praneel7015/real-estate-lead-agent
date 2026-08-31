"""
Coordinator agent — orchestrates the lead pipeline.
Runs deterministic state machine first; falls back to LLM only for ambiguous cases.
"""
from __future__ import annotations

import json
import logging
import os
import re
import uuid
from datetime import datetime, timezone
from typing import Optional

from src.data.models import Lead, Message, CoordinatorDecision
from src.coordinator.state_machine import transition

logger = logging.getLogger(__name__)

_COORDINATOR_PROMPT = """You are the routing brain for a real estate lead-management system.
You do NOT talk to the lead directly — you decide which specialist agent to invoke next.
You are ONLY called when the deterministic state machine doesn't have an unambiguous next step.

STATE MACHINE reference (trust this over your own judgment when it clearly applies):
  NEW -> on new lead: invoke CONVERSATION_AGENT -> CONTACTED
  AWAITING_REPLY -> on inbound: invoke CONVERSATION_AGENT -> REPLIED
  AWAITING_REPLY -> 24h timer: send nudge -> stays AWAITING_REPLY
  AWAITING_REPLY -> 72h timer: -> STALE
  REPLIED + is_complete=false: invoke CONVERSATION_AGENT -> AWAITING_REPLY
  REPLIED + is_complete=true: invoke scoring -> SCORED
  SCORED: invoke SCHEDULING_AGENT.find_slots -> SLOT_OFFERED
  SLOT_OFFERED + confirm: book_slot -> BOOKED
  BOOKED + reminder timer: send reminder -> REMINDED
  BOOKED + cancel: cancel -> CANCELLED
  BOOKED/SLOT_OFFERED + reschedule: find_slots -> SLOT_OFFERED
  REMINDED + meeting done: alert_salesperson -> DONE

YOUR JOB for ambiguous cases:
1. Match to closest existing rule.
2. If genuinely no match: return escalate=true, leave state unchanged.
3. Never invoke more than one agent per turn.
4. Never skip states.

OUTPUT FORMAT — ONLY this JSON:
{
  "action": "<invoke_conversation_agent|invoke_scheduling_agent|invoke_scoring|notify_salesperson|escalate|no_action>",
  "next_state": "<state or 'unchanged'>",
  "reasoning": "<one sentence>",
  "escalate": <true|false>
}"""


def _strip_fences(text: str) -> str:
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    return text.strip()


def _llm_resolve(lead: Lead, event: str, payload: dict) -> CoordinatorDecision:
    from src.integrations.gemini_client import generate_text

    context = (
        f"{_COORDINATOR_PROMPT}\n\n"
        f"Current lead state: {lead.state}\n"
        f"Event received: {event}\n"
        f"Payload: {json.dumps(payload)}\n"
        "Decide what to do next. Return only the JSON."
    )
    data = json.loads(_strip_fences(generate_text(context)))
    return CoordinatorDecision(
        action=data.get("action", "no_action"),
        next_state=data.get("next_state", "unchanged"),
        reasoning=data.get("reasoning", ""),
        escalate=bool(data.get("escalate", False)),
    )


async def process_event(lead_id: str, event: str, payload: dict) -> None:
    """Main coordinator entry point — loads lead, runs SM, executes actions."""
    from src.data import firestore_client
    from src.integrations import telegram_client as twilio_client
    from src.integrations.notify import alert_salesperson
    from src.conversation.agent import _handle_message_internal as handle_message
    from src.conversation.scoring import score_lead
    from src.scheduling.agent import (
        find_slots,
        book_slot,
        cancel,
        reschedule,
        build_slot_offer_message,
        build_confirmation_message,
        build_reminder_message,
        build_cancellation_message,
    )
    from src.tasks.followups import (
        schedule_followup,
        cancel_pending_followups,
        schedule_meeting_done,
        schedule_reminder_before_appt,
    )

    lead = firestore_client.get_lead(lead_id)
    if not lead:
        logger.error("Lead %s not found", lead_id)
        return

    new_state, actions = transition(lead, event, payload)

    if not actions:
        # LLM fallback for ambiguous transitions
        try:
            decision = _llm_resolve(lead, event, payload)
            actions = [decision.action]
            if decision.next_state != "unchanged":
                new_state = decision.next_state
            if decision.escalate:
                logger.warning("Escalated: lead=%s event=%s reason=%s", lead_id, event, decision.reasoning)
                return
        except Exception as exc:
            logger.error("LLM resolver failed: %s", exc)
            return

    lead.state = new_state
    firestore_client.save_lead(lead)

    for action in actions:
        try:
            await _execute_action(
                action, lead, payload,
                firestore_client=firestore_client,
                twilio_client=twilio_client,
                alert_salesperson=alert_salesperson,
                handle_message=handle_message,
                score_lead=score_lead,
                find_slots=find_slots,
                book_slot=book_slot,
                cancel=cancel,
                reschedule=reschedule,
                build_slot_offer_message=build_slot_offer_message,
                build_confirmation_message=build_confirmation_message,
                build_reminder_message=build_reminder_message,
                build_cancellation_message=build_cancellation_message,
                schedule_followup=schedule_followup,
                cancel_pending_followups=cancel_pending_followups,
                schedule_meeting_done=schedule_meeting_done,
                schedule_reminder_before_appt=schedule_reminder_before_appt,
            )
        except Exception as exc:
            logger.error("Action %s failed for lead %s: %s", action, lead_id, exc)


async def _execute_action(action: str, lead: Lead, payload: dict, **deps) -> None:
    fc = deps["firestore_client"]
    tg = deps["twilio_client"]  # now telegram_client, aliased for minimal diff

    def _send(msg: str) -> None:
        """Send via Telegram if chat_id is known, otherwise log."""
        if lead.telegram_chat_id:
            tg.send_message(lead.telegram_chat_id, msg)
        else:
            logger.info(
                "No telegram_chat_id for lead %s — message queued: %s",
                lead.lead_id, msg[:80],
            )

    if action == "send_opening_message":
        msg = (
            f"Hi {lead.name}! Thanks for your interest in finding a property. "
            "I'm your AI real estate assistant. "
            "Could you tell me more about what you're looking for?"
        )
        _send(msg)
        _store_outbound(fc, lead, msg)

    elif action == "invoke_conversation_agent":
        messages = fc.get_messages(lead.lead_id)
        incoming = payload.get("body", "")
        try:
            result = deps["handle_message"](lead, messages, incoming)
            reply = result.reply_text
            is_complete = result.is_complete
            intent = result.intent
        except Exception as exc:
            logger.error("Conversation agent failed for %s: %s", lead.lead_id, exc)
            reply = "Thanks for your message! Let me look into that and get back to you shortly."
            is_complete = False
            intent = "qualifying"
        _send(reply)
        _store_outbound(fc, lead, reply)
        fc.save_lead(lead)

        if intent == "cancel":
            await process_event(lead.lead_id, "cancel_requested", {})
        elif intent == "reschedule":
            await process_event(lead.lead_id, "reschedule_requested", {})
        elif intent == "confirm" and lead.state in ("SLOT_OFFERED", "RESCHEDULE_REQUESTED"):
            await process_event(lead.lead_id, "slot_confirmed", payload)
        else:
            await process_event(
                lead.lead_id, "is_complete_true", {"is_complete": is_complete}
            )

    elif action == "invoke_scoring":
        score, reason = deps["score_lead"](lead)
        lead.score = score
        lead.score_reason = reason
        fc.save_lead(lead)
        await process_event(lead.lead_id, "scored", {"score": score})

    elif action in ("find_slots", "send_slots_message", "send_reschedule_slots"):
        slots = deps["find_slots"](lead.availability)
        if lead.telegram_chat_id and slots:
            # Build slot list for buttons and store on lead for callback resolution
            slot_data = [
                {
                    "label": f"📅 {s.start.strftime('%a %d %b, %I:%M %p')}",
                    "start_iso": s.start.isoformat(),
                    "end_iso": s.end.isoformat(),
                }
                for s in slots[:3]
            ]
            lead.offered_slots = slot_data
            fc.save_lead(lead)
            from src.integrations.telegram_client import send_slot_buttons
            send_slot_buttons(lead.telegram_chat_id, lead.lead_id, slot_data)
        else:
            msg = deps["build_slot_offer_message"](lead, slots)
            _send(msg)
            _store_outbound(fc, lead, msg)

    elif action == "book_slot":
        slot = payload.get("slot")
        if slot:
            try:
                appt = deps["book_slot"](lead.lead_id, slot, lead)
            except Exception as exc:
                logger.error("book_slot failed for %s: %s", lead.lead_id, exc)
                if lead.telegram_chat_id:
                    tg.send_message(
                        lead.telegram_chat_id,
                        "Sorry, I couldn't book that slot. Please pick another time.",
                    )
                return
            lead.appointment = {
                "eventId": appt.event_id,
                "start": appt.start.isoformat(),
                "end": appt.end.isoformat(),
            }
            fc.save_lead(lead)
            if lead.telegram_chat_id:
                from src.integrations.telegram_client import send_booking_confirmation_buttons
                slot_label = appt.start.strftime("%a %d %b, %I:%M %p")
                send_booking_confirmation_buttons(lead.telegram_chat_id, lead.lead_id, slot_label)
            else:
                msg = deps["build_confirmation_message"](lead, appt)
                _send(msg)
                _store_outbound(fc, lead, msg)
            try:
                deps["schedule_meeting_done"](lead.lead_id, appt.end)
            except Exception as exc:
                logger.warning("Could not schedule meeting_done task: %s", exc)

    elif action == "reschedule_slot":
        slot = payload.get("slot")
        appt_data = lead.appointment or {}
        event_id = appt_data.get("eventId", "")
        if slot and event_id:
            try:
                appt = deps["reschedule"](lead.lead_id, slot, event_id)
            except Exception as exc:
                logger.error("reschedule_slot failed for %s: %s", lead.lead_id, exc)
                if lead.telegram_chat_id:
                    tg.send_message(
                        lead.telegram_chat_id,
                        "Sorry, I couldn't reschedule. Please try another slot.",
                    )
                return
            lead.appointment = {
                "eventId": appt.event_id,
                "start": appt.start.isoformat(),
                "end": appt.end.isoformat(),
            }
            fc.save_lead(lead)
            if lead.telegram_chat_id:
                from src.integrations.telegram_client import send_booking_confirmation_buttons
                slot_label = appt.start.strftime("%a %d %b, %I:%M %p")
                send_booking_confirmation_buttons(lead.telegram_chat_id, lead.lead_id, slot_label)
            else:
                msg = deps["build_confirmation_message"](lead, appt)
                _send(msg)
                _store_outbound(fc, lead, msg)
            try:
                deps["schedule_meeting_done"](lead.lead_id, appt.end)
            except Exception as exc:
                logger.warning("Could not schedule meeting_done task: %s", exc)

    elif action == "schedule_reminder":
        appt_data = lead.appointment or {}
        if appt_data.get("start"):
            try:
                appt_start = datetime.fromisoformat(appt_data["start"])
                deps["schedule_reminder_before_appt"](lead.lead_id, appt_start)
            except Exception as exc:
                logger.warning("Could not schedule reminder task: %s", exc)
        else:
            try:
                deps["schedule_followup"](lead.lead_id, 24, "reminder_24h_before")
            except Exception as exc:
                logger.warning("Could not schedule reminder task: %s", exc)

    elif action == "schedule_24h_nudge":
        try:
            deps["schedule_followup"](lead.lead_id, 24, "nudge_24h")
        except Exception as exc:
            logger.warning("Could not schedule 24h nudge: %s", exc)

    elif action == "schedule_72h_timer":
        try:
            deps["schedule_followup"](lead.lead_id, 72, "nudge_72h")
        except Exception as exc:
            logger.warning("Could not schedule 72h timer: %s", exc)

    elif action == "send_nudge":
        msg = (
            f"Hi {lead.name}, just checking in — are you still looking for a property? "
            "Happy to help whenever you're ready!"
        )
        _send(msg)
        _store_outbound(fc, lead, msg)

    elif action == "send_reminder":
        appt_data = lead.appointment or {}
        from src.data.models import Appointment
        from datetime import datetime
        if appt_data and appt_data.get("start") and appt_data.get("end"):
            appt = Appointment(
                event_id=appt_data.get("eventId", ""),
                lead_id=lead.lead_id,
                start=datetime.fromisoformat(appt_data["start"]),
                end=datetime.fromisoformat(appt_data["end"]),
            )
            msg = deps["build_reminder_message"](lead, appt)
            _send(msg)
            _store_outbound(fc, lead, msg)

    elif action == "cancel_calendar":
        appt_data = lead.appointment or {}
        if appt_data.get("eventId"):
            deps["cancel"](lead.lead_id, appt_data["eventId"])

    elif action == "send_cancellation_ack":
        msg = deps["build_cancellation_message"](lead)
        _send(msg)
        _store_outbound(fc, lead, msg)

    elif action == "cancel_nudges":
        deps["cancel_pending_followups"](lead.lead_id)

    elif action == "alert_salesperson":
        from src.data.models import Appointment
        appt_data = lead.appointment or {}
        appt = None
        if appt_data and appt_data.get("start") and appt_data.get("end"):
            appt = Appointment(
                event_id=appt_data.get("eventId", ""),
                lead_id=lead.lead_id,
                start=datetime.fromisoformat(appt_data["start"]),
                end=datetime.fromisoformat(appt_data["end"]),
            )
        deps["alert_salesperson"](lead, appt)
        lead.salesperson_alerted = True
        fc.save_lead(lead)

    elif action in ("stop", "no_action"):
        pass

    else:
        logger.warning("Unknown action: %s for lead %s", action, lead.lead_id)


def _store_outbound(fc, lead: Lead, body: str) -> None:
    msg = Message(
        message_id=str(uuid.uuid4()),
        lead_id=lead.lead_id,
        direction="outbound",
        body=body,
        timestamp=datetime.now(tz=timezone.utc),
    )
    fc.add_message(lead.lead_id, msg)
