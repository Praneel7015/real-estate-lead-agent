"""
Firestore persistence layer.
Falls back gracefully when google-cloud-firestore is not configured.
"""
from __future__ import annotations

import os
from datetime import datetime
from typing import Optional

from src.data.models import Lead, Message


def _get_client():
    try:
        from google.cloud import firestore  # type: ignore

        project = os.environ.get("GOOGLE_CLOUD_PROJECT")
        return firestore.Client(project=project)
    except Exception as exc:
        raise RuntimeError(
            "Firestore client unavailable. Set GOOGLE_CLOUD_PROJECT and "
            "GOOGLE_APPLICATION_CREDENTIALS."
        ) from exc


def _lead_from_doc(data: dict) -> Lead:
    for dt_field in ("created_at", "last_reply_at"):
        val = data.get(dt_field)
        if val and not isinstance(val, datetime):
            data[dt_field] = datetime.fromisoformat(str(val))
    return Lead(**{k: v for k, v in data.items() if k in Lead.__dataclass_fields__})


def get_lead(lead_id: str) -> Optional[Lead]:
    db = _get_client()
    doc = db.collection("leads").document(lead_id).get()
    if not doc.exists:
        return None
    return _lead_from_doc(doc.to_dict())


def save_lead(lead: Lead) -> None:
    db = _get_client()
    data = {k: v for k, v in lead.__dict__.items() if v is not None}
    for dt_field in ("created_at", "last_reply_at"):
        if isinstance(data.get(dt_field), datetime):
            data[dt_field] = data[dt_field].isoformat()
    db.collection("leads").document(lead.lead_id).set(data, merge=True)


def add_message(lead_id: str, message: Message) -> None:
    db = _get_client()
    data = {
        "message_id": message.message_id,
        "lead_id": message.lead_id,
        "direction": message.direction,
        "body": message.body,
        "timestamp": message.timestamp.isoformat(),
    }
    db.collection("leads").document(lead_id).collection("messages").document(
        message.message_id
    ).set(data)


def get_messages(lead_id: str) -> list[Message]:
    db = _get_client()
    docs = (
        db.collection("leads")
        .document(lead_id)
        .collection("messages")
        .order_by("timestamp")
        .stream()
    )
    results = []
    for doc in docs:
        d = doc.to_dict()
        results.append(
            Message(
                message_id=d["message_id"],
                lead_id=d["lead_id"],
                direction=d["direction"],
                body=d["body"],
                timestamp=datetime.fromisoformat(d["timestamp"]),
            )
        )
    return results


def list_leads(state: Optional[str] = None) -> list[Lead]:
    db = _get_client()
    ref = db.collection("leads")
    if state:
        ref = ref.where("state", "==", state)
    return [_lead_from_doc(doc.to_dict()) for doc in ref.stream()]
