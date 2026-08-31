"""
Lead scoring — Gemini score with rule-based fallback.
"""
from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.data.models import Lead

from src.integrations.gemini_client import generate_text

_SCORING_PROMPT_TEMPLATE = """You are scoring a real estate lead. Use this rubric exactly:
- HIGH: budget stated and realistic, timeline ready now or within ~30 days.
- MEDIUM: budget fits but timeline vague, or unclear budget but strong engagement.
- LOW: budget out of range, no clear timeline, low engagement.

Given:
Budget: {budget}
Preferences: {property_preferences}
Availability/timeline: {availability}

Return ONLY this JSON:
{{"score": "HIGH | MEDIUM | LOW", "reason": "<one sentence for salesperson>"}}"""


def _strip_fences(text: str) -> str:
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    return text.strip()


def _rule_based_score(lead: "Lead") -> str:
    """Fast heuristic pass — no LLM needed."""
    has_budget = bool(lead.budget)
    has_availability = bool(lead.availability)
    has_prefs = bool(lead.property_preferences)

    if has_budget and has_availability:
        return "HIGH"
    if has_budget or (has_prefs and has_availability):
        return "MEDIUM"
    return "LOW"


def _gemini_score_and_reason(lead: "Lead") -> tuple[str | None, str]:
    prompt = _SCORING_PROMPT_TEMPLATE.format(
        budget=lead.budget or "unknown",
        property_preferences=lead.property_preferences or "unknown",
        availability=lead.availability or "unknown",
    )
    raw = _strip_fences(generate_text(prompt))
    data = json.loads(raw)
    score = data.get("score", "").upper().strip()
    if score not in ("HIGH", "MEDIUM", "LOW"):
        score = None
    reason = data.get("reason", "")
    return score, reason


def score_lead(lead: "Lead") -> tuple[str, str]:
    """
    Return (score, reason_sentence).
    Prefer Gemini score when valid; fall back to rules.
    """
    fallback = _rule_based_score(lead)
    try:
        gemini_score, reason = _gemini_score_and_reason(lead)
        score = gemini_score or fallback
        if not reason:
            reason = f"Lead scored {score} based on provided information."
    except Exception:
        score = fallback
        reason = f"Lead scored {score} based on provided information."
    return score, reason
