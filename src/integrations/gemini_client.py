"""Shared Gemini client using the google-genai SDK (GenAI SDK)."""
from __future__ import annotations

import os

MODEL = "gemini-2.0-flash"


def generate_text(prompt: str) -> str:
    """Call Gemini and return the response text."""
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise EnvironmentError("GEMINI_API_KEY environment variable is not set.")
    from google import genai  # type: ignore

    client = genai.Client(api_key=api_key)
    response = client.models.generate_content(model=MODEL, contents=prompt)
    return response.text or ""
