from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

STATES = [
    "NEW",
    "CONTACTED",
    "AWAITING_REPLY",
    "REPLIED",
    "SCORED",
    "SLOT_OFFERED",
    "BOOKED",
    "REMINDED",
    "RESCHEDULE_REQUESTED",
    "CANCELLED",
    "STALE",
    "DONE",
]


@dataclass
class Lead:
    lead_id: str
    phone: str
    name: str
    state: str = "NEW"
    budget: Optional[str] = None
    property_preferences: Optional[str] = None
    availability: Optional[str] = None
    score: Optional[str] = None  # HIGH | MEDIUM | LOW
    score_reason: Optional[str] = None
    created_at: Optional[datetime] = None
    last_reply_at: Optional[datetime] = None
    followups_sent: list = field(default_factory=list)
    appointment: Optional[dict] = None  # {eventId, start, end}
    salesperson_alerted: bool = False
    telegram_chat_id: Optional[str] = None


@dataclass
class Appointment:
    event_id: str
    lead_id: str
    start: datetime
    end: datetime


@dataclass
class Message:
    message_id: str
    lead_id: str
    direction: str  # inbound | outbound
    body: str
    timestamp: datetime


@dataclass
class TimeSlot:
    start: datetime
    end: datetime


@dataclass
class ConversationResult:
    reply_text: str
    extracted: dict  # {budget, property_preferences, availability}
    intent: str  # qualifying | confirm | cancel | reschedule | off_topic
    score: Optional[str]
    is_complete: bool


@dataclass
class CoordinatorDecision:
    action: str  # invoke_conversation_agent | invoke_scheduling_agent | invoke_scoring | notify_salesperson | escalate | no_action
    next_state: str
    reasoning: str
    escalate: bool
