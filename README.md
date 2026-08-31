# ZealEstate AI — Autonomous Real Estate Lead Agent

> **Live Demo:** https://praneel7015.github.io/real-estate-lead-agent  
> **API:** https://real-estate-lead-agent-637tks4tda-uc.a.run.app/docs  
> **Telegram Bot:** [@ZealEstateAIBot](https://t.me/ZealEstateAIBot)

An autonomous multi-agent AI system that handles the **entire real estate lead lifecycle** — from first contact to booked meeting — with **zero human intervention**. Built on Gemini, Google Cloud Run, Firestore, and the Telegram Bot API.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                         LEAD INTAKE                                  │
│  GitHub Pages Form  ──►  POST /leads  ──►  Firestore (leads)        │
│                                 │                                    │
│                         Telegram deep-link shown to user             │
└─────────────────────────────────┬───────────────────────────────────┘
                                  │
                    ┌─────────────▼─────────────┐
                    │    COORDINATOR AGENT       │
                    │  (Cloud Run / FastAPI)     │
                    │                           │
                    │  Deterministic State       │
                    │  Machine:                  │
                    │  NEW → CONTACTED →         │
                    │  REPLIED → SCORED →        │
                    │  SLOT_OFFERED → BOOKED →   │
                    │  REMINDED → DONE           │
                    └──┬──────────┬─────────────┘
                       │          │
          ┌────────────▼──┐  ┌───▼──────────────────┐
          │  CONVERSATION  │  │   SCHEDULING AGENT   │
          │  AGENT         │  │                      │
          │  Gemini Flash  │  │  Gemini Flash        │
          │                │  │  + Google Calendar   │
          │  Qualifies     │  │                      │
          │  lead via      │  │  Finds free slots,   │
          │  Telegram:     │  │  books appointments, │
          │  • Budget      │  │  sends reminders     │
          │  • Preferences │  └──────────┬───────────┘
          │  • Availability│             │
          │  • Scoring     │   ┌─────────▼──────────┐
          └────────┬───────┘   │  Google Calendar   │
                   │           │  (real events)     │
          ┌────────▼───────┐   └────────────────────┘
          │  Telegram Bot  │
          │  @ZealEstateAI │  Inline keyboards for:
          │                │  • Property type
          │                │  • Budget range
          │                │  • Availability
          │                │  • Slot selection
          └────────────────┘

     ASYNC LAYER                    PERSISTENCE
  ┌──────────────────┐         ┌──────────────────┐
  │  Cloud Tasks     │         │    Firestore      │
  │  • 24h nudge     │         │  • leads          │
  │  • 72h stale     │         │  • messages       │
  │  • 24h reminder  │         │  • appointments   │
  └──────────────────┘         └──────────────────┘
```

### State Machine
```
NEW ──[lead_created]──► CONTACTED ──[intake_complete]──► SCORED
                            │                               │
                     [timer_24h]                    [invoke_scoring]
                            ▼                               ▼
                     AWAITING_REPLY              SLOT_OFFERED
                            │                       │         │
                    [inbound_msg]            [confirmed]  [reschedule]
                            ▼                   ▼               ▼
                         REPLIED             BOOKED    RESCHEDULE_REQUESTED
                            │                  │
                   [is_complete=true]     [timer_reminder]
                            ▼                  ▼
                          SCORED           REMINDED
                                               │
                                        [meeting_done]
                                               ▼
                                             DONE ──► salesperson_alerted
```

---

## Tech Stack

| Layer | Technology |
|---|---|
| LLM | Gemini 2.0 Flash (`google-genai` GenAI SDK) |
| Backend | FastAPI + Python 3.11 on Cloud Run |
| Database | Google Cloud Firestore (Native mode) |
| Async tasks | Google Cloud Tasks |
| Calendar | Google Calendar API (ADC via service account) |
| Messaging | Telegram Bot API |
| Frontend | GitHub Pages (static HTML) |
| CI/CD | GitHub Actions |
| Auth | Service Account + ADC (no key files) |

---

## Local Setup

### Prerequisites
- Python 3.11+
- GCP project with Firestore (Native mode) enabled
- Gemini API key from [Google AI Studio](https://aistudio.google.com/app/apikey)
- Telegram Bot token from [@BotFather](https://t.me/BotFather)

### Run locally

```bash
# 1. Clone the repo
git clone https://github.com/Praneel7015/real-estate-lead-agent.git
cd real-estate-lead-agent

# 2. Create virtual environment
python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS/Linux:
source .venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Set environment variables
cp .env.example .env
# Edit .env with your values (see required vars below)

# 5. Run the server
uvicorn src.main:app --reload --port 8000
```

API docs available at `http://localhost:8000/docs`  
Lead intake form: open `frontend/lead-form/index.html` in a browser

### Required environment variables

| Variable | Description |
|---|---|
| `GOOGLE_CLOUD_PROJECT` | GCP project ID |
| `GEMINI_API_KEY` | From Google AI Studio (uses `google-genai` SDK) |
| `TELEGRAM_BOT_TOKEN` | From @BotFather |
| `TELEGRAM_BOT_USERNAME` | Your bot's username (no @) |
| `CLOUD_RUN_URL` | Deployed Cloud Run URL (required for Cloud Tasks callbacks) |
| `CALENDAR_ID` | Google Calendar ID (share calendar with service account first) |
| `SALESPERSON_EMAIL` | Email to alert when meeting is done |
| `SMTP_HOST` / `SMTP_PORT` / `SMTP_USER` / `SMTP_PASS` / `FROM_EMAIL` | Email config for salesperson alerts |
| `CLOUD_TASKS_QUEUE` | Cloud Tasks queue name |
| `CLOUD_TASKS_LOCATION` | Cloud Tasks region (e.g. `us-central1`) |

---

## Cloud Run Deployment

Deployment is fully automated via **GitHub Actions** on every push to `master`.

### One-time GCP setup

```bash
# 1. Enable required APIs
gcloud services enable \
  run.googleapis.com \
  firestore.googleapis.com \
  cloudtasks.googleapis.com \
  calendar-json.googleapis.com \
  artifactregistry.googleapis.com \
  --project=YOUR_PROJECT_ID

# 2. Create service account
gcloud iam service-accounts create real-estate-agent-sa \
  --project=YOUR_PROJECT_ID

# 3. Grant roles
for ROLE in roles/datastore.user roles/cloudtasks.enqueuer \
            roles/run.admin roles/artifactregistry.writer \
            roles/iam.serviceAccountUser; do
  gcloud projects add-iam-policy-binding YOUR_PROJECT_ID \
    --member="serviceAccount:real-estate-agent-sa@YOUR_PROJECT_ID.iam.gserviceaccount.com" \
    --role="$ROLE"
done

# 4. Create Firestore database
gcloud firestore databases create --location=us-central1 --project=YOUR_PROJECT_ID

# 5. Create Cloud Tasks queue
gcloud tasks queues create lead-followups --location=us-central1 --project=YOUR_PROJECT_ID
```

### GitHub Secrets required

Add these to your repo → Settings → Secrets → Actions:

`GCP_PROJECT_ID`, `GCP_SA_KEY`, `GEMINI_API_KEY`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_BOT_USERNAME`, `CALENDAR_ID`, `SALESPERSON_EMAIL`, `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASS`, `FROM_EMAIL`, `CLOUD_TASKS_QUEUE`

### Register Telegram webhook (after first deploy)

```powershell
Invoke-RestMethod `
  -Uri "https://api.telegram.org/bot<YOUR_TOKEN>/setWebhook" `
  -Method POST -ContentType "application/json" `
  -Body '{"url":"https://YOUR_CLOUD_RUN_URL/webhook/telegram","drop_pending_updates":true}'
```

### Google Calendar setup

1. Enable Calendar API: `gcloud services enable calendar-json.googleapis.com`
2. Share your Google Calendar with `real-estate-agent-sa@YOUR_PROJECT_ID.iam.gserviceaccount.com` (Make changes to events)
3. Copy Calendar ID from Calendar Settings → add as `CALENDAR_ID` secret

---

## API Reference

| Method | Path | Description |
|---|---|---|
| `GET` | `/health` | Health check + version |
| `POST` | `/leads` | Create a new lead |
| `GET` | `/leads` | List all leads (optional `?state=BOOKED`) |
| `GET` | `/leads/{lead_id}` | Get lead details |
| `GET` | `/appointments` | List all booked appointments |
| `POST` | `/webhook/telegram` | Telegram Bot webhook |
| `POST` | `/webhook/twilio` | Twilio WhatsApp webhook (legacy) |
| `POST` | `/internal/tasks/nudge_24h` | 24h follow-up (Cloud Tasks) |
| `POST` | `/internal/tasks/nudge_72h` | 72h stale check (Cloud Tasks) |
| `POST` | `/internal/tasks/reminder_24h_before` | Pre-meeting reminder |

---

## Running Tests

```bash
python -m pytest tests/ -v
```

---

## How It Works (User Journey)

1. **Lead submits form** at the GitHub Pages URL → lead saved to Firestore instantly
2. **Success page shows a Telegram deep-link** button: "Open Telegram Chat"
3. **Lead taps Start** in Telegram → bot greets them with inline keyboard buttons
4. **Guided intake** (no free-text required):
   - 🏢 Property type buttons
   - 💰 Budget range buttons  
   - 📅 Availability buttons
5. **Gemini scores the lead** (HIGH / MEDIUM / LOW) based on their profile
6. **Calendar slots appear as buttons** — lead taps one to book
7. **Appointment created** in Google Calendar + saved to Firestore
8. **24h reminder sent** before the appointment via Telegram
9. **Salesperson alerted** by email when meeting is marked done
