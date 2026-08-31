"""
Cloud Tasks follow-up scheduler and route handlers.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, Request

router = APIRouter(tags=["internal-tasks"])


def _get_tasks_client():
    try:
        from google.cloud import tasks_v2  # type: ignore

        return tasks_v2.CloudTasksClient()
    except ImportError as exc:
        raise RuntimeError("google-cloud-tasks is required.") from exc


def _queue_path() -> str:
    client = _get_tasks_client()
    project = os.environ["GOOGLE_CLOUD_PROJECT"]
    location = os.environ.get("CLOUD_TASKS_LOCATION", "us-central1")
    queue = os.environ.get("CLOUD_TASKS_QUEUE", "lead-followups")
    return client.queue_path(project, location, queue)


def schedule_reminder_before_appt(lead_id: str, appt_start: datetime) -> None:
    """Schedule reminder 24 hours before appointment (min 15 minutes from now)."""
    now = datetime.now(tz=timezone.utc)
    reminder_at = appt_start - timedelta(hours=24)
    if reminder_at <= now:
        delay_hours = 0.25  # 15 minutes
    else:
        delay_hours = (reminder_at - now).total_seconds() / 3600
    schedule_followup(lead_id, delay_hours, "reminder_24h_before")


def schedule_followup(lead_id: str, delay_hours: float, kind: str) -> None:
    """Create a Cloud Tasks task to call /internal/tasks/{kind}?lead_id=..."""
    client = _get_tasks_client()
    base_url = os.environ.get("CLOUD_RUN_URL", "http://localhost:8000")
    url = f"{base_url}/internal/tasks/{kind}?lead_id={lead_id}"

    schedule_time = datetime.now(tz=timezone.utc) + timedelta(hours=delay_hours)

    from google.protobuf import timestamp_pb2  # type: ignore

    ts = timestamp_pb2.Timestamp()
    ts.FromDatetime(schedule_time)

    task = {
        "name": f"{_queue_path()}/tasks/{kind}-{lead_id}-{int(schedule_time.timestamp())}",
        "http_request": {
            "http_method": "POST",
            "url": url,
            "headers": {"Content-Type": "application/json"},
        },
        "schedule_time": ts,
    }
    client.create_task(request={"parent": _queue_path(), "task": task})


def schedule_meeting_done(lead_id: str, meeting_end: datetime) -> None:
    """Schedule the meeting_done event to fire at the appointment end time."""
    now = datetime.now(tz=timezone.utc)
    delay_hours = max(0, (meeting_end - now).total_seconds() / 3600)
    schedule_followup(lead_id, delay_hours, "meeting_done")


def cancel_pending_followups(lead_id: str) -> None:
    """Delete all pending tasks for this lead by listing and filtering by name."""
    client = _get_tasks_client()
    queue = _queue_path()
    for task in client.list_tasks(request={"parent": queue}):
        if lead_id in task.name:
            try:
                client.delete_task(request={"name": task.name})
            except Exception:
                pass  # Already executed or deleted


@router.post("/nudge_24h")
async def handle_nudge_24h(lead_id: str, request: Request):
    """Fire 24-hour nudge for a lead that hasn't replied."""
    from src.coordinator.agent import process_event

    try:
        await process_event(lead_id, "timer_24h", {})
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    return {"status": "ok", "lead_id": lead_id, "event": "timer_24h"}


@router.post("/nudge_72h")
async def handle_nudge_72h(lead_id: str, request: Request):
    """Fire 72-hour timer — marks lead as STALE."""
    from src.coordinator.agent import process_event

    try:
        await process_event(lead_id, "timer_72h", {})
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    return {"status": "ok", "lead_id": lead_id, "event": "timer_72h"}


@router.post("/reminder_24h_before")
async def handle_reminder_24h_before(lead_id: str, request: Request):
    """Fire 24-hours-before-appointment reminder."""
    from src.coordinator.agent import process_event

    try:
        await process_event(lead_id, "timer_reminder", {})
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    return {"status": "ok", "lead_id": lead_id, "event": "timer_reminder"}


@router.post("/meeting_done")
async def handle_meeting_done(lead_id: str, request: Request):
    """
    Called after the meeting time has passed — triggers REMINDED → DONE,
    which fires the salesperson alert.

    Schedule this via Cloud Tasks at the appointment end time.
    Can also be triggered manually during the demo.
    """
    from src.coordinator.agent import process_event

    try:
        await process_event(lead_id, "meeting_done", {})
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    return {"status": "ok", "lead_id": lead_id, "event": "meeting_done"}
