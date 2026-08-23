"""
Integration tests for FastAPI routes.
All external dependencies (Firestore, Twilio, Gemini, coordinator) are mocked.
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
        phone="+19175550001",
        name="Alex Test",
        state="NEW",
        created_at=datetime.now(tz=timezone.utc),
    )


# ---------------------------------------------------------------------------
# GET /health
# ---------------------------------------------------------------------------

class TestHealthEndpoint:
    def test_health_returns_ok(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}


# ---------------------------------------------------------------------------
# POST /leads
# ---------------------------------------------------------------------------

class TestCreateLead:
    @patch("src.data.firestore_client.save_lead")
    @patch("src.coordinator.agent.process_event", new_callable=AsyncMock)
    def test_create_lead_returns_201(self, mock_process, mock_save, client):
        payload = {
            "name": "Jane Buyer",
            "phone": "+19175550002",
            "property_preferences": "3-bed apartment",
            "budget": "$500k",
        }
        resp = client.post("/leads", json=payload)
        assert resp.status_code == 201
        body = resp.json()
        assert "lead_id" in body
        assert body["status"] == "created"

    @patch("src.data.firestore_client.save_lead")
    @patch("src.coordinator.agent.process_event", new_callable=AsyncMock)
    def test_create_lead_fires_process_event(self, mock_process, mock_save, client):
        payload = {"name": "John", "phone": "+10000000000"}
        client.post("/leads", json=payload)
        mock_process.assert_called_once()
        args = mock_process.call_args
        assert args[0][1] == "lead_created"

    def test_create_lead_missing_name_returns_422(self, client):
        resp = client.post("/leads", json={"phone": "+10000000000"})
        assert resp.status_code == 422

    def test_create_lead_missing_phone_returns_422(self, client):
        resp = client.post("/leads", json={"name": "No Phone"})
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# GET /leads
# ---------------------------------------------------------------------------

class TestListLeads:
    @patch("src.data.firestore_client.list_leads")
    def test_list_leads_returns_list(self, mock_list, client, sample_lead):
        mock_list.return_value = [sample_lead]
        resp = client.get("/leads")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)
        assert len(resp.json()) == 1
        assert resp.json()[0]["name"] == "Alex Test"

    @patch("src.data.firestore_client.list_leads")
    def test_list_leads_empty(self, mock_list, client):
        mock_list.return_value = []
        resp = client.get("/leads")
        assert resp.status_code == 200
        assert resp.json() == []

    @patch("src.data.firestore_client.list_leads")
    def test_list_leads_filters_by_state(self, mock_list, client, sample_lead):
        mock_list.return_value = [sample_lead]
        resp = client.get("/leads?state=NEW")
        assert resp.status_code == 200
        mock_list.assert_called_with(state="NEW")


# ---------------------------------------------------------------------------
# GET /leads/{lead_id}
# ---------------------------------------------------------------------------

class TestGetLead:
    @patch("src.data.firestore_client.get_lead")
    def test_get_lead_found(self, mock_get, client, sample_lead):
        mock_get.return_value = sample_lead
        resp = client.get(f"/leads/{sample_lead.lead_id}")
        assert resp.status_code == 200
        assert resp.json()["lead_id"] == sample_lead.lead_id

    @patch("src.data.firestore_client.get_lead")
    def test_get_lead_not_found_returns_404(self, mock_get, client):
        mock_get.return_value = None
        resp = client.get("/leads/nonexistent-id")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# POST /webhook/twilio
# ---------------------------------------------------------------------------

class TestTwilioWebhook:
    @patch("src.coordinator.router._validate_twilio_signature", return_value=True)
    @patch("src.data.firestore_client.add_message")
    @patch("src.data.firestore_client.save_lead")
    @patch("src.data.firestore_client.list_leads")
    @patch("src.coordinator.agent.process_event", new_callable=AsyncMock)
    def test_webhook_known_lead(self, mock_process, mock_list, mock_save, mock_add, mock_sig, client, sample_lead):
        sample_lead.phone = "+19175550003"
        mock_list.return_value = [sample_lead]

        resp = client.post(
            "/webhook/twilio",
            data={"From": "whatsapp:+19175550003", "Body": "Hello"},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        assert resp.status_code == 200
        mock_process.assert_called_once()
        args = mock_process.call_args[0]
        assert args[1] == "inbound_message"

    @patch("src.coordinator.router._validate_twilio_signature", return_value=True)
    @patch("src.data.firestore_client.add_message")
    @patch("src.data.firestore_client.save_lead")
    @patch("src.data.firestore_client.list_leads")
    @patch("src.coordinator.agent.process_event", new_callable=AsyncMock)
    def test_webhook_unknown_lead_creates_new(self, mock_process, mock_list, mock_save, mock_add, mock_sig, client):
        mock_list.return_value = []

        resp = client.post(
            "/webhook/twilio",
            data={"From": "whatsapp:+19991112222", "Body": "Hi there"},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        assert resp.status_code == 200
        mock_save.assert_called()

    @patch("src.coordinator.router._validate_twilio_signature", return_value=False)
    def test_webhook_invalid_signature_returns_403(self, mock_sig, client):
        resp = client.post(
            "/webhook/twilio",
            data={"From": "whatsapp:+19175550003", "Body": "Hello"},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# POST /internal/tasks/...
# ---------------------------------------------------------------------------

class TestInternalTaskEndpoints:
    @patch("src.coordinator.agent.process_event", new_callable=AsyncMock)
    def test_nudge_24h(self, mock_process, client):
        resp = client.post("/internal/tasks/nudge_24h?lead_id=test-lead")
        assert resp.status_code == 200
        mock_process.assert_called_with("test-lead", "timer_24h", {})

    @patch("src.coordinator.agent.process_event", new_callable=AsyncMock)
    def test_nudge_72h(self, mock_process, client):
        resp = client.post("/internal/tasks/nudge_72h?lead_id=test-lead")
        assert resp.status_code == 200
        mock_process.assert_called_with("test-lead", "timer_72h", {})

    @patch("src.coordinator.agent.process_event", new_callable=AsyncMock)
    def test_reminder(self, mock_process, client):
        resp = client.post("/internal/tasks/reminder_24h_before?lead_id=test-lead")
        assert resp.status_code == 200
        mock_process.assert_called_with("test-lead", "timer_reminder", {})

    @patch("src.coordinator.agent.process_event", new_callable=AsyncMock)
    def test_meeting_done(self, mock_process, client):
        resp = client.post("/internal/tasks/meeting_done?lead_id=test-lead")
        assert resp.status_code == 200
        mock_process.assert_called_with("test-lead", "meeting_done", {})
