"""
Salesperson alert — sends an email summary when a lead's meeting is done.
Uses sendgrid if SENDGRID_API_KEY is set, otherwise falls back to SMTP.
"""
from __future__ import annotations

import os
import smtplib
from email.mime.text import MIMEText
from typing import Optional

from src.data.models import Appointment, Lead


def _build_email_body(lead: Lead, appointment: Optional[Appointment]) -> str:
    lines = [
        "Real Estate Lead Summary",
        "=" * 40,
        f"Name:        {lead.name}",
        f"Phone:       {lead.phone}",
        f"Score:       {lead.score or 'N/A'} — {lead.score_reason or ''}",
        f"Budget:      {lead.budget or 'Not stated'}",
        f"Preferences: {lead.property_preferences or 'Not stated'}",
        f"Availability:{lead.availability or 'Not stated'}",
        "",
    ]
    if appointment:
        lines += [
            "Appointment",
            "-" * 20,
            f"Start: {appointment.start.isoformat()}",
            f"End:   {appointment.end.isoformat()}",
            f"Event ID: {appointment.event_id}",
        ]
    return "\n".join(lines)


def _send_via_sendgrid(to: str, subject: str, body: str) -> None:
    import sendgrid  # type: ignore
    from sendgrid.helpers.mail import Mail  # type: ignore

    sg = sendgrid.SendGridAPIClient(api_key=os.environ["SENDGRID_API_KEY"])
    mail = Mail(
        from_email=os.environ.get("FROM_EMAIL", "noreply@realestate.ai"),
        to_emails=to,
        subject=subject,
        plain_text_content=body,
    )
    sg.send(mail)


def _send_via_smtp(to: str, subject: str, body: str) -> None:
    smtp_host = os.environ.get("SMTP_HOST", "localhost")
    smtp_port = int(os.environ.get("SMTP_PORT", "587"))
    smtp_user = os.environ.get("SMTP_USER", "")
    smtp_pass = os.environ.get("SMTP_PASS", "")
    from_email = os.environ.get("FROM_EMAIL", "noreply@realestate.ai")

    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = from_email
    msg["To"] = to

    with smtplib.SMTP(smtp_host, smtp_port) as server:
        if smtp_user:
            server.starttls()
            server.login(smtp_user, smtp_pass)
        server.sendmail(from_email, [to], msg.as_string())


def alert_salesperson(lead: Lead, appointment: Optional[Appointment]) -> None:
    """Send lead summary email to the salesperson."""
    to = os.environ.get("SALESPERSON_EMAIL")
    if not to:
        raise EnvironmentError("SALESPERSON_EMAIL environment variable is not set.")

    subject = f"Lead ready for follow-up: {lead.name} [{lead.score or 'unscored'}]"
    body = _build_email_body(lead, appointment)

    if os.environ.get("SENDGRID_API_KEY"):
        _send_via_sendgrid(to, subject, body)
    else:
        _send_via_smtp(to, subject, body)
