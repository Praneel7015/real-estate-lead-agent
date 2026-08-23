"""
Unit tests for lead scoring — mocks the Gemini call.
"""
from __future__ import annotations

import pytest
from unittest.mock import patch, MagicMock
from src.data.models import Lead
from src.conversation.scoring import score_lead, _rule_based_score


def _make_lead(budget=None, prefs=None, availability=None) -> Lead:
    return Lead(
        lead_id="test-1",
        phone="+10000000000",
        name="Test Lead",
        budget=budget,
        property_preferences=prefs,
        availability=availability,
    )


class TestRuleBasedScore:
    def test_high_when_budget_and_availability(self):
        lead = _make_lead(budget="$400k", availability="available this weekend")
        assert _rule_based_score(lead) == "HIGH"

    def test_medium_when_only_budget(self):
        lead = _make_lead(budget="$300k–$400k")
        assert _rule_based_score(lead) == "MEDIUM"

    def test_medium_when_prefs_and_availability(self):
        lead = _make_lead(prefs="3-bed apartment downtown", availability="next Monday morning")
        assert _rule_based_score(lead) == "MEDIUM"

    def test_low_when_nothing(self):
        lead = _make_lead()
        assert _rule_based_score(lead) == "LOW"

    def test_low_when_only_prefs(self):
        lead = _make_lead(prefs="3-bed house with garden")
        assert _rule_based_score(lead) == "LOW"


class TestScoreLead:
    def _mock_gemini(self, reason_text: str):
        """Patch google.generativeai so no real API call is made."""
        mock_response = MagicMock()
        mock_response.text = f'{{"score": "HIGH", "reason": "{reason_text}"}}'

        mock_model = MagicMock()
        mock_model.generate_content.return_value = mock_response

        mock_genai = MagicMock()
        mock_genai.GenerativeModel.return_value = mock_model
        return mock_genai

    def test_score_lead_high_with_mock(self):
        lead = _make_lead(budget="$500k", availability="Saturday morning")

        mock_response = MagicMock()
        mock_response.text = '{"score": "HIGH", "reason": "Strong lead with clear budget and near-term availability."}'
        mock_model = MagicMock()
        mock_model.generate_content.return_value = mock_response
        mock_genai = MagicMock()
        mock_genai.GenerativeModel.return_value = mock_model

        with patch.dict("os.environ", {"GEMINI_API_KEY": "fake-key"}):
            with patch.dict("sys.modules", {"google.generativeai": mock_genai}):
                score, reason = score_lead(lead)

        assert score == "HIGH"
        assert "Strong lead" in reason or "HIGH" in reason or "scored" in reason.lower()

    def test_score_lead_falls_back_on_no_api_key(self):
        lead = _make_lead(budget="$500k", availability="weekends")
        import os
        env_without_key = {k: v for k, v in os.environ.items() if k != "GEMINI_API_KEY"}
        with patch.dict("os.environ", env_without_key, clear=True):
            score, reason = score_lead(lead)
        assert score == "HIGH"
        assert "HIGH" in reason or "scored" in reason.lower()

    def test_score_lead_medium_no_gemini(self):
        lead = _make_lead(budget="$400k")
        with patch.dict("os.environ", {}, clear=True):
            score, reason = score_lead(lead)
        assert score == "MEDIUM"

    def test_score_lead_low_no_info(self):
        lead = _make_lead()
        with patch.dict("os.environ", {}, clear=True):
            score, reason = score_lead(lead)
        assert score == "LOW"
        assert reason  # Should always return something
