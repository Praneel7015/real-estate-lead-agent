"""
Conversation agent — wraps Gemini 1.5 Flash to qualify leads over WhatsApp.
"""
from __future__ import annotations

import json
import os
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.data.models import Lead, Message

from src.data.models import ConversationResult

_SYSTEM_PROMPT = """You are a real estate lead qualification assistant messaging a prospective
buyer over WhatsApp on behalf of a property agency. Your job in this
conversation is to naturally gather three things, one or two at a time,
never all at once:

1. Budget — an approximate price range they're comfortable with
2. What they're looking for — property type, location, size, must-haves
3. Availability — when they're free for a short call or viewing this week

RULES
- Sound like a helpful, low-pressure human assistant, not a form. Never
  send a numbered list of questions. Ask one natural question per message.
- Mirror the lead's language and tone (formal/informal) and reply in
  whichever language they write in.
- Keep every message under ~3 sentences. This is WhatsApp, not email.
- Never invent property listings, prices, or availability you don't have.
  If asked something outside your scope, say a human will follow up.
- If the lead's message is a cancellation, reschedule request, or
  confirmation of a proposed time, set "intent" accordingly instead of
  continuing to qualify them.
- Do not pressure, guilt, or use urgency/scarcity tactics.
- Only ask about what's still missing based on the conversation history.

OUTPUT FORMAT — respond with ONLY this JSON object, no other text:
{
  "reply_text": "<WhatsApp message to send>",
  "extracted": {
    "budget": "<number, range as string, or null>",
    "property_preferences": "<string or null>",
    "availability": "<string or null>"
  },
  "intent": "<qualifying | confirm | cancel | reschedule | off_topic>",
  "is_complete": <true if all three fields now known, else false>
}"""


def _get_gemini_model():
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise EnvironmentError(
            "GEMINI_API_KEY environment variable is not set. "
            "Set it before using the conversation agent."
        )
    import google.generativeai as genai  # type: ignore

    genai.configure(api_key=api_key)
    return genai.GenerativeModel("gemini-1.5-flash")


def _strip_fences(text: str) -> str:
    """Remove markdown code fences if present."""
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    return text.strip()


def _build_history(messages: list["Message"], incoming_text: str) -> list[dict]:
    history = []
    for msg in messages:
        role = "user" if msg.direction == "inbound" else "model"
        history.append({"role": role, "parts": [msg.body]})
    history.append({"role": "user", "parts": [incoming_text]})
    return history


def handle_message(lead_id: str, incoming_text: str) -> ConversationResult:
    """Public interface per spec §6. Loads lead + messages from Firestore."""
    from src.data.firestore_client import get_lead, get_messages

    lead = get_lead(lead_id)
    if lead is None:
        raise ValueError(f"Lead {lead_id} not found")
    messages = get_messages(lead_id)
    return _handle_message_internal(lead, messages, incoming_text)


def _handle_message_internal(
    lead: "Lead",
    messages: list["Message"],
    incoming_text: str,
) -> ConversationResult:
    """Call Gemini and return a structured ConversationResult."""
    model = _get_gemini_model()

    history = _build_history(messages, incoming_text)
    prompt_parts = [_SYSTEM_PROMPT, "\n\nConversation so far:\n"]
    for turn in history[:-1]:
        role_label = "Lead" if turn["role"] == "user" else "Agent"
        prompt_parts.append(f"{role_label}: {turn['parts'][0]}")
    prompt_parts.append(f"\nLatest lead message: {incoming_text}")
    prompt_parts.append("\nRespond with only the JSON object.")

    full_prompt = "\n".join(prompt_parts)
    response = model.generate_content(full_prompt)
    raw = _strip_fences(response.text)
    data = json.loads(raw)

    extracted = data.get("extracted", {})
    # Merge extracted fields onto lead for scoring context
    if extracted.get("budget"):
        lead.budget = extracted["budget"]
    if extracted.get("property_preferences"):
        lead.property_preferences = extracted["property_preferences"]
    if extracted.get("availability"):
        lead.availability = extracted["availability"]

    return ConversationResult(
        reply_text=data["reply_text"],
        extracted=extracted,
        intent=data.get("intent", "qualifying"),
        score=None,
        is_complete=bool(data.get("is_complete", False)),
    )
