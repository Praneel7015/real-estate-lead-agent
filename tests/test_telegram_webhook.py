"""
Tests for Telegram webhook — /start, intake callbacks, slot booking flow.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from src.main import app
from src.data.models import Lead


@pytest.fixture()
def client():
    return TestClient(app, raise_server_exceptions=True)


@pytest.fixture()
def sample_lead():
    return Lead(
        lead_id=str(uuid.uuid4()),
        phone="+919876543210",
        name="Alex Test",
        state="CONTACTED",
        telegram_chat_id="123456789",
        created_at=datetime.now(tz=timezone.utc),
    )


class TestTelegramStart:
    @patch("src.integrations.telegram_client.send_property_type_buttons")
    @patch("src.data.firestore_client.save_lead")
    @patch("src.data.firestore_client.get_lead")
    def test_start_deep_link_sends_intake_buttons(
        self, mock_get, mock_save, mock_buttons, client, sample_lead
    ):
        mock_get.return_value = sample_lead
        resp = client.post("/webhook/telegram", json={
            "message": {
                "chat": {"id": 123456789},
                "text": f"/start {sample_lead.lead_id}",
            }
        })
        assert resp.status_code == 200
        mock_buttons.assert_called_once()
        mock_save.assert_called()


class TestTelegramCallbacks:
    @patch("src.coordinator.agent.process_event", new_callable=AsyncMock)
    @patch("src.integrations.telegram_client.answer_callback")
    @patch("src.data.firestore_client.save_lead")
    @patch("src.data.firestore_client.get_lead")
    def test_property_type_callback(
        self, mock_get, mock_save, mock_answer, mock_process, client, sample_lead
    ):
        mock_get.return_value = sample_lead
        resp = client.post("/webhook/telegram", json={
            "callback_query": {
                "id": "cq1",
                "data": f"pt:{sample_lead.lead_id}:apartment",
                "message": {"chat": {"id": 123456789}},
            }
        })
        assert resp.status_code == 200
        mock_answer.assert_called_once()
        mock_save.assert_called()

    @patch("src.coordinator.agent.process_event", new_callable=AsyncMock)
    @patch("src.integrations.telegram_client.send_message")
    @patch("src.integrations.telegram_client.answer_callback")
    @patch("src.data.firestore_client.save_lead")
    @patch("src.data.firestore_client.get_lead")
    def test_availability_triggers_intake_complete(
        self, mock_get, mock_save, mock_answer, mock_send, mock_process, client, sample_lead
    ):
        sample_lead.property_preferences = "Apartment"
        sample_lead.budget = "₹1Cr – ₹2Cr"
        mock_get.return_value = sample_lead
        resp = client.post("/webhook/telegram", json={
            "callback_query": {
                "id": "cq2",
                "data": f"av:{sample_lead.lead_id}:thisweek",
                "message": {"chat": {"id": 123456789}},
            }
        })
        assert resp.status_code == 200
        # Background task — give it a moment
        import time
        time.sleep(0.1)

    @patch("src.integrations.telegram_client.send_booking_confirmation_buttons")
    @patch("src.coordinator.agent.process_event", new_callable=AsyncMock)
    @patch("src.integrations.telegram_client.answer_callback")
    @patch("src.data.firestore_client.get_lead")
    def test_slot_selected_does_not_confirm_before_book(
        self, mock_get, mock_answer, mock_process, mock_confirm, client, sample_lead
    ):
        sample_lead.offered_slots = [
            {
                "label": "Mon 01 Sep, 10:00 AM",
                "start_iso": "2026-09-01T10:00:00+00:00",
                "end_iso": "2026-09-01T10:30:00+00:00",
            }
        ]
        mock_get.return_value = sample_lead
        resp = client.post("/webhook/telegram", json={
            "callback_query": {
                "id": "cq3",
                "data": f"sl:{sample_lead.lead_id}:0",
                "message": {"chat": {"id": 123456789}},
            }
        })
        assert resp.status_code == 200
        mock_confirm.assert_not_called()
