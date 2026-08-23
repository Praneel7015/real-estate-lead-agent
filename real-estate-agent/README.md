# Real Estate Lead Agent

An AI-powered real estate lead qualification and appointment scheduling system. The system automatically contacts new leads via WhatsApp, qualifies them through natural conversation (gathering budget, preferences, and availability), scores them, books calendar appointments, sends reminders, and alerts the salesperson when a meeting is complete.

## Architecture Overview

The system is a multi-agent pipeline orchestrated by a deterministic state machine. When a new lead arrives, the **Coordinator** fires `lead_created`, transitions the lead through states (`NEW → CONTACTED → AWAITING_REPLY → REPLIED → SCORED → SLOT_OFFERED → BOOKED → REMINDED → DONE`), and dispatches work to specialist agents:

- **Conversation Agent** (Gemini 1.5 Flash): Qualifies leads over WhatsApp, extracting budget, property preferences, and availability.
- **Scoring Module**: Rule-based scoring (HIGH/MEDIUM/LOW) with Gemini-generated reason sentence.
- **Scheduling Agent** (Gemini + Google Calendar): Finds free slots, books appointments, sends WhatsApp scheduling messages.
- **Twilio**: Sends and receives WhatsApp messages.
- **Cloud Tasks**: Handles 24h/72h follow-up nudges and 24h-before appointment reminders.
- **Firestore**: Persists lead state, messages, and appointments.

See [`plan.md`](plan.md) for a full architecture diagram and state machine reference.

## Prerequisites

1. **GCP Project** with these APIs enabled:
   - Firestore (Native mode)
   - Cloud Tasks
   - Google Calendar API
   - Cloud Run (for deployment)
2. **Service Account** with roles: `roles/datastore.user`, `roles/cloudtasks.enqueuer`, `roles/calendar.app.created`
3. **Gemini API Key** from [Google AI Studio](https://aistudio.google.com/app/apikey)
4. **Twilio account** with WhatsApp Sandbox enabled (see [WhatsApp Sandbox setup](docs/whatsapp-sandbox.md))
5. **Python 3.11+**

## Local Setup

```bash
# Clone and enter the project
cd real-estate-agent

# Create and activate a virtual environment
python -m venv .venv
.venv\Scripts\activate  # Windows
# source .venv/bin/activate  # macOS/Linux

# Install dependencies
pip install -r requirements.txt

# Configure environment variables
cp .env.example .env
# Edit .env with your actual values

# Load env vars and run the server
uvicorn src.main:app --reload --port 8000
```

The API will be available at `http://localhost:8000`. Interactive docs at `http://localhost:8000/docs`.

Open `frontend/lead-form/index.html` in a browser to test the lead intake form.

## Joining the Twilio WhatsApp Sandbox

See [`docs/whatsapp-sandbox.md`](docs/whatsapp-sandbox.md) for step-by-step sandbox setup. Key steps:

1. Sign in to [Twilio Console](https://console.twilio.com) → Messaging → Try WhatsApp
2. Send the join code from your phone to the sandbox number
3. Set the webhook URL to `https://your-service.run.app/webhook/twilio`
4. Set `TWILIO_WHATSAPP_FROM=whatsapp:+14155238886` in your `.env`

## Cloud Run Deployment

```bash
# Build and push container
gcloud builds submit --tag gcr.io/$PROJECT_ID/real-estate-agent

# Deploy to Cloud Run
gcloud run deploy real-estate-agent \
  --image gcr.io/$PROJECT_ID/real-estate-agent \
  --platform managed \
  --region us-central1 \
  --allow-unauthenticated \
  --set-env-vars GOOGLE_CLOUD_PROJECT=$PROJECT_ID \
  --set-env-vars GEMINI_API_KEY=$GEMINI_API_KEY \
  --set-env-vars TWILIO_ACCOUNT_SID=$TWILIO_ACCOUNT_SID \
  --set-env-vars TWILIO_AUTH_TOKEN=$TWILIO_AUTH_TOKEN \
  --set-env-vars SALESPERSON_EMAIL=$SALESPERSON_EMAIL
```

Update `CLOUD_RUN_URL` in `.env` with the deployed service URL.

## Running Tests

```bash
# From the real-estate-agent directory
python -m pytest tests/ -v
```

Tests cover:
- Every state machine transition (including invalid transitions)
- Lead scoring logic (HIGH/MEDIUM/LOW) with mocked Gemini
- Google Calendar client with mocked API responses

## API Reference

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Health check |
| `POST` | `/leads` | Create new lead |
| `GET` | `/leads` | List all leads (optional `?state=BOOKED`) |
| `GET` | `/leads/{lead_id}` | Get lead details |
| `POST` | `/webhook/twilio` | Twilio inbound WhatsApp webhook |
| `POST` | `/internal/tasks/nudge_24h` | 24h follow-up (Cloud Tasks) |
| `POST` | `/internal/tasks/nudge_72h` | 72h stale check (Cloud Tasks) |
| `POST` | `/internal/tasks/reminder_24h_before` | Pre-meeting reminder (Cloud Tasks) |

## Known Limitations

- **Twilio sandbox**: The sandbox uses a shared WhatsApp number and requires leads to opt-in by sending a join code. Production use requires Meta business API approval via Twilio.
- **Calendar timezone**: All calendar slots are in UTC. For production, pass timezone info from the lead's location.
- **Slot confirmation parsing**: The current implementation expects the coordinator to receive a `slot_confirmed` event with a slot payload. A full production system would add NLP to parse the lead's reply and identify the confirmed slot.
- **No Dockerfile included**: Add a `FROM python:3.11-slim` Dockerfile for containerized Cloud Run deployment.
