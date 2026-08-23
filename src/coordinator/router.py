"""
FastAPI route handlers for lead intake and Twilio webhook.
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Request, Form, Header
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
async def create_lead(body: LeadCreateRequest):
    """Intake a new lead from the web form or API."""
    from src.data import firestore_client
    from src.coordinator.agent import process_event

    lead = Lead(
        lead_id=str(uuid.uuid4()),
        phone=body.phone,
        name=body.name,
        state="NEW",
        budget=body.budget,
        property_preferences=body.property_preferences,
        created_at=datetime.now(tz=timezone.utc),
    )
    firestore_client.save_lead(lead)

    # Kick off the pipeline asynchronously
    await process_event(lead.lead_id, "lead_created", {})

    return {"lead_id": lead.lead_id, "status": "created"}


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


@router.get("/leads")
async def list_leads(state: Optional[str] = None):
    """List all leads, optionally filtered by state."""
    from src.data import firestore_client

    leads = firestore_client.list_leads(state=state)
    return [lead.__dict__ for lead in leads]


@router.get("/leads/{lead_id}")
async def get_lead(lead_id: str):
    """Get a single lead by ID."""
    from src.data import firestore_client

    lead = firestore_client.get_lead(lead_id)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    return lead.__dict__
