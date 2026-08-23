"""
Extraction helpers — parse structured fields from raw lead text.
Used as fallback / pre-processing before sending to the LLM.
"""
from __future__ import annotations

import re
from typing import Optional


_BUDGET_PATTERNS = [
    re.compile(r"\$[\d,]+(?:\s*[-–]\s*\$[\d,]+)?", re.IGNORECASE),
    re.compile(r"[\d,]+(?:\s*[-–]\s*[\d,]+)?\s*(?:k|K|thousand|lakh|crore|million)", re.IGNORECASE),
    re.compile(r"(?:budget|price|range|afford)[^\d]*[\d,]+", re.IGNORECASE),
]

_AVAILABILITY_KEYWORDS = [
    "monday", "tuesday", "wednesday", "thursday", "friday",
    "saturday", "sunday", "morning", "afternoon", "evening",
    "weekend", "weekday", "anytime", "available", "free",
    "tomorrow", "next week", "this week",
]


def extract_budget(text: str) -> Optional[str]:
    for pat in _BUDGET_PATTERNS:
        m = pat.search(text)
        if m:
            return m.group(0).strip()
    return None


def extract_availability(text: str) -> Optional[str]:
    lower = text.lower()
    matches = [kw for kw in _AVAILABILITY_KEYWORDS if kw in lower]
    if matches:
        # Return first 60 chars of surrounding context
        return text[:60].strip()
    return None


def extract_property_preferences(text: str) -> Optional[str]:
    keywords = [
        "bedroom", "bed", "bath", "apartment", "house", "condo",
        "villa", "studio", "sqft", "sq ft", "garage", "garden",
        "pool", "downtown", "suburb", "school", "near",
    ]
    lower = text.lower()
    if any(kw in lower for kw in keywords):
        return text[:120].strip()
    return None
