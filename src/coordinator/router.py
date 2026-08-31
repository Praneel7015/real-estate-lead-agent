"""
FastAPI route handlers for lead intake and Twilio webhook.
"""
from __future__ import annotations

import dataclasses
import os
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request, Form, Header
from pydantic import BaseModel

from src.data.models import Lead, Message

router = APIRouter(tags=["leads"])


def _validate_twilio_signature(request_url: str, post_data: dict, signature: str) -> bool:
    """Validate the X-Twilio-Signature header to reject spoofed webhooks."""
    auth_token = os.environ.get("TWILIO_AUTH_TOKEN", "")
    if not auth_token:
        return True  # Skip in dev if not configured
    try:
        from twilio.request_validator import RequestValidator  # type: ignore
        validator = RequestValidator(auth_token)
        return validator.validate(request_url, post_data, signature)
    except Exception:
        return False


class LeadCreateRequest(BaseModel):
    name: str
    phone: str
    property_preferences: Optional[str] = None
    budget: Optional[str] = None


@router.post("/leads", status_code=201)
async def create_lead(body: LeadCreateRequest, background_tasks: BackgroundTasks):
    """Intake a new lead from the web form or API."""
    try:
        from src.data import firestore_client
        from src.coordinator.agent import process_event
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Import error: {exc}")

    lead = Lead(
        lead_id=str(uuid.uuid4()),
        phone=body.phone,
        name=body.name,
        state="NEW",
        budget=body.budget,
        property_preferences=body.property_preferences,
        created_at=datetime.now(tz=timezone.utc),
    )

    try:
        firestore_client.save_lead(lead)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Firestore save failed: {exc}")

    async def _run_pipeline():
        import logging
        try:
            await process_event(lead.lead_id, "lead_created", {})
        except Exception as exc:
            logging.getLogger(__name__).error("process_event failed for %s: %s", lead.lead_id, exc)

    background_tasks.add_task(_run_pipeline)

    return {"lead_id": lead.lead_id, "status": "created"}


@router.post("/webhook/telegram")
async def telegram_webhook(request: Request, background_tasks: BackgroundTasks):
    """Receive inbound Telegram updates: messages and inline keyboard callbacks."""
    import logging
    from src.integrations import telegram_client as tg
    from src.data import firestore_client
    from src.coordinator.agent import process_event

    body = await request.json()
    chat_id, text, start_payload, cq_id, cq_data = tg.parse_update(body)

    if not chat_id:
        return {"ok": True}

    log = logging.getLogger(__name__)

    # ── /start <lead_id> deep-link ──────────────────────────────────────────
    if start_payload:
        lead = firestore_client.get_lead(start_payload)
        if lead:
            lead.telegram_chat_id = chat_id
            lead.state = "CONTACTED"
            firestore_client.save_lead(lead)
            tg.send_property_type_buttons(chat_id, lead.lead_id, lead.name)
        else:
            tg.send_message(chat_id, "Sorry, I couldn't find your registration. Please fill out the form again.")
        return {"ok": True}

    # ── Inline keyboard callback (button press) ─────────────────────────────
    if cq_id and cq_data:
        tg.answer_callback(cq_id)
        parts = cq_data.split(":", 2)
        action_type = parts[0] if parts else ""
        lead_id = parts[1] if len(parts) > 1 else ""
        value = parts[2] if len(parts) > 2 else ""

        lead = firestore_client.get_lead(lead_id) if lead_id else None
        if not lead:
            tg.send_message(chat_id, "Session expired. Please fill out the form again.")
            return {"ok": True}

        if action_type == "pt":  # property type selected
            labels = {
                "apartment": "🏢 Apartment", "house": "🏡 House",
                "villa": "🏰 Villa", "commercial": "🏪 Commercial", "other": "Other",
            }
            if value != "other":
                lead.property_preferences = labels.get(value, value)
                firestore_client.save_lead(lead)
                tg.send_budget_buttons(chat_id, lead.lead_id)
            else:
                tg.send_message(chat_id, "No problem! Tell me what kind of property you have in mind.")

        elif action_type == "bd":  # budget selected
            budget_labels = {
                "lt50L": "Under ₹50L", "50-100L": "₹50L – ₹1Cr",
                "1-2Cr": "₹1Cr – ₹2Cr", "gt2Cr": "₹2Cr+",
            }
            if value != "custom":
                lead.budget = budget_labels.get(value, value)
                firestore_client.save_lead(lead)
                tg.send_availability_question(chat_id, lead.lead_id)
            else:
                tg.send_message(chat_id, "Sure! What's your budget? (e.g. ₹80L, 1.5 crore, etc.)")

        elif action_type == "av":  # availability selected
            avail_labels = {
                "thisweek": "This week", "nextweek": "Next week", "weekends": "Weekends",
            }
            if value != "custom":
                lead.availability = avail_labels.get(value, value)
                firestore_client.save_lead(lead)
                tg.send_message(chat_id,
                    "Perfect! I have everything I need. Let me find some available slots for you — one moment! 🔍")
                async def _intake_complete():
                    try:
                        await process_event(lead.lead_id, "intake_complete", {})
                    except Exception as exc:
                        log.error("intake_complete failed for %s: %s", lead.lead_id, exc)
                        tg.send_message(chat_id, "Sorry, something went wrong finding slots. Please try again in a moment.")
                background_tasks.add_task(_intake_complete)
            else:
                tg.send_message(chat_id, "When works best for you? (e.g. *Tuesday evening*, *this weekend*, *anytime this week*)")

        elif action_type == "sl":  # slot selected
            try:
                idx = int(value)
                offered = lead.offered_slots
                if 0 <= idx < len(offered):
                    slot_info = offered[idx]
                    from src.data.models import TimeSlot
                    from datetime import datetime as dt
                    slot = TimeSlot(
                        start=dt.fromisoformat(slot_info["start_iso"]),
                        end=dt.fromisoformat(slot_info["end_iso"]),
                    )
                    async def _book():
                        try:
                            await process_event(lead.lead_id, "slot_confirmed", {"slot": slot})
                        except Exception as exc:
                            log.error("slot booking failed: %s", exc)
                            tg.send_message(
                                chat_id,
                                "Sorry, I couldn't book that slot. Please try another time.",
                            )
                    background_tasks.add_task(_book)
                else:
                    tg.send_message(chat_id, "Sorry, that slot is no longer available. Let me find new ones.")
                    await process_event(lead.lead_id, "reschedule_requested", {})
            except (ValueError, IndexError):
                tg.send_message(chat_id, "Something went wrong picking that slot. Please try again.")

        elif action_type == "rs":  # reschedule
            tg.send_message(chat_id, "No problem! Let me find some new times for you.")
            async def _reschedule():
                try:
                    await process_event(lead.lead_id, "reschedule_requested", {})
                except Exception as exc:
                    log.error("reschedule failed: %s", exc)
            background_tasks.add_task(_reschedule)

        elif action_type == "cx":  # cancel
            tg.send_message(chat_id, "Your appointment has been cancelled. Feel free to reach out anytime if you'd like to reschedule! 😊")
            async def _cancel():
                try:
                    await process_event(lead.lead_id, "cancel_requested", {})
                except Exception as exc:
                    log.error("cancel failed: %s", exc)
            background_tasks.add_task(_cancel)

        return {"ok": True}

    # ── Regular inbound text message ────────────────────────────────────────
    lead = firestore_client.get_lead_by_telegram_chat_id(chat_id)
    if not lead:
        tg.send_message(chat_id, "Hi! Please fill out our property search form first to get started.")
        return {"ok": True}

    # Store inbound message
    inbound_msg = Message(
        message_id=str(uuid.uuid4()),
        lead_id=lead.lead_id,
        direction="inbound",
        body=text,
        timestamp=datetime.now(tz=timezone.utc),
    )
    firestore_client.add_message(lead.lead_id, inbound_msg)
    lead.last_reply_at = inbound_msg.timestamp
    firestore_client.save_lead(lead)

    # ── Intake state: fill in whichever field is still missing ───────────────
    if lead.state == "CONTACTED":
        if not lead.property_preferences:
            lead.property_preferences = text
            firestore_client.save_lead(lead)
            tg.send_budget_buttons(chat_id, lead.lead_id)
            return {"ok": True}

        if not lead.budget:
            lead.budget = text
            firestore_client.save_lead(lead)
            tg.send_availability_question(chat_id, lead.lead_id)
            return {"ok": True}

        if not lead.availability:
            lead.availability = text
            firestore_client.save_lead(lead)
            tg.send_message(chat_id,
                "Perfect! Let me find some available slots for you — one moment! 🔍")
            async def _complete_from_text():
                try:
                    await process_event(lead.lead_id, "intake_complete", {})
                except Exception as exc:
                    log.error("intake_complete (text) failed for %s: %s", lead.lead_id, exc)
                    tg.send_message(chat_id, "Sorry, something went wrong. Please try again in a moment.")
            background_tasks.add_task(_complete_from_text)
            return {"ok": True}

    # ── All other states: Gemini-powered conversation ────────────────────────
    async def _run():
        try:
            await process_event(lead.lead_id, "inbound_message", {"body": text})
        except Exception as exc:
            log.error("Telegram pipeline error for %s: %s", lead.lead_id, exc)
            tg.send_message(chat_id, "Sorry, I hit a snag — I'll get back to you shortly! 🙏")

    background_tasks.add_task(_run)
    return {"ok": True}


@router.post("/webhook/twilio")
async def twilio_webhook(request: Request):
    """Receive inbound WhatsApp messages from Twilio."""
    from src.data import firestore_client
    from src.integrations.twilio_client import parse_inbound_webhook
    from src.coordinator.agent import process_event

    form_data = dict(await request.form())

    # Validate Twilio signature in production
    twilio_sig = request.headers.get("X-Twilio-Signature", "")
    request_url = str(request.url)
    if not _validate_twilio_signature(request_url, form_data, twilio_sig):
        raise HTTPException(status_code=403, detail="Invalid Twilio signature")
    from_number, body_text = parse_inbound_webhook(form_data)

    # Find lead by phone number
    leads = firestore_client.list_leads()
    lead = next((l for l in leads if l.phone == from_number), None)

    if not lead:
        # Unknown sender — create a placeholder lead
        lead = Lead(
            lead_id=str(uuid.uuid4()),
            phone=from_number,
            name="Unknown",
            state="NEW",
            created_at=datetime.now(tz=timezone.utc),
        )
        firestore_client.save_lead(lead)

    # Store the inbound message
    msg = Message(
        message_id=str(uuid.uuid4()),
        lead_id=lead.lead_id,
        direction="inbound",
        body=body_text,
        timestamp=datetime.now(tz=timezone.utc),
    )
    firestore_client.add_message(lead.lead_id, msg)
    lead.last_reply_at = msg.timestamp
    firestore_client.save_lead(lead)

    await process_event(lead.lead_id, "inbound_message", {"body": body_text})

    # Twilio expects a 200 TwiML response (empty is fine for messaging)
    return {"status": "ok"}


@router.get("/appointments")
async def list_appointments():
    """List all booked appointments."""
    from src.data.firestore_client import _get_client
    from datetime import datetime
    try:
        db = _get_client()
        docs = db.collection("appointments").stream()
        return [doc.to_dict() for doc in docs]
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/leads")
async def list_leads(state: Optional[str] = None):
    """List all leads, optionally filtered by state."""
    from src.data import firestore_client

    leads = firestore_client.list_leads(state=state)
    return [dataclasses.asdict(lead) for lead in leads]


@router.get("/leads/{lead_id}")
async def get_lead(lead_id: str):
    """Get a single lead by ID."""
    from src.data import firestore_client

    lead = firestore_client.get_lead(lead_id)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    return dataclasses.asdict(lead)
