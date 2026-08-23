# Real Estate Lead Agent — Architecture Plan

## System Overview

```
Web Form (HTML)
     │
     ▼ POST /leads
┌────────────────────────────────────────────────────┐
│              FastAPI (Cloud Run)                   │
│  ┌──────────────────────────────────────────────┐  │
│  │           Coordinator Agent                  │  │
│  │  ┌──────────────┐   ┌─────────────────────┐  │  │
│  │  │ State Machine│──▶│   Action Executor   │  │  │
│  │  │ (pure logic) │   │  (dispatches work)  │  │  │
│  │  └──────────────┘   └──────┬──────────────┘  │  │
│  └─────────────────────────────┼────────────────┘  │
│                                │                    │
│        ┌───────────────────────┼──────────────┐    │
│        ▼                       ▼              ▼    │
│  ┌───────────┐    ┌──────────────────┐  ┌─────────┐│
│  │Conversation│   │ Scheduling Agent │  │Scoring  ││
│  │  Agent    │   │ (Calendar API)   │  │ Module  ││
│  │ (Gemini)  │   │   (Gemini)       │  │ (Rules) ││
│  └─────┬─────┘   └────────┬─────────┘  └────┬────┘│
└────────┼──────────────────┼────────────────┼─────┘
         │                  │                │
         ▼                  ▼                ▼
    Twilio WhatsApp    Google Calendar   Firestore
    (send/receive)     (book slots)      (lead data)
         │
         ▼
     Cloud Tasks
    (24h/72h nudge,
     24h reminder)
         │
         ▼
    Salesperson Email
    (done alert)
```

## Lead State Machine

```
NEW ──[lead_created]──▶ CONTACTED
                              │
                    [inbound_message]
                              │
                              ▼
AWAITING_REPLY ◀──────── REPLIED ──[is_complete=true]──▶ SCORED
     │                    │                                  │
  [timer_24h]     [is_complete=false]                   [scored]
     │                                                       │
     ▼                                                       ▼
AWAITING_REPLY ──[timer_72h]──▶ STALE            SLOT_OFFERED
                                                       │
                                            [slot_confirmed]
                                                       │
                                                       ▼
                                                    BOOKED ──[cancel]──▶ CANCELLED
                                                       │
                                              [timer_reminder]
                                                       │
                                                       ▼
                                                  REMINDED ──[meeting_done]──▶ DONE
```

## Agent Responsibilities

| Agent | Trigger | Output |
|-------|---------|--------|
| Coordinator | Every event | State transition + action dispatch |
| Conversation | Inbound message | Reply text + extracted fields |
| Scoring | is_complete=true | HIGH/MEDIUM/LOW + reason |
| Scheduling | Scored lead | Slot list + booking messages |

## Data Flow

1. Lead submits web form → `POST /leads` → Lead created in Firestore
2. Coordinator fires `lead_created` → `CONTACTED` → sends opening WhatsApp
3. Cloud Tasks schedules 24h nudge
4. Lead replies → Twilio webhook → `POST /webhook/twilio`
5. Coordinator fires `inbound_message` → `REPLIED`
6. Conversation Agent extracts budget/prefs/availability, replies naturally
7. When all fields known: `is_complete=true` → `SCORED`
8. Scoring module rates lead HIGH/MEDIUM/LOW
9. Scheduling Agent finds 3 calendar slots, messages lead
10. Lead confirms slot → Appointment booked in Google Calendar
11. 24h before: reminder sent via WhatsApp
12. After meeting: salesperson alerted by email → `DONE`
