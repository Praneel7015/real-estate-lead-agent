# Code Review — Real Estate Lead Agent
## Reviewer: Code Review Agent (parallel)
## Date: 2026-08-23
## Scope: Full spec compliance review of builder output

---

## 1. Repo Structure

| Path | Present | Non-empty |
|------|---------|-----------|
| `src/main.py` | ✅ | ✅ |
| `src/coordinator/agent.py` | ✅ | ✅ |
| `src/coordinator/state_machine.py` | ✅ | ✅ |
| `src/coordinator/router.py` | ✅ | ✅ |
| `src/conversation/agent.py` | ✅ | ✅ |
| `src/conversation/extraction.py` | ✅ | ✅ |
| `src/conversation/scoring.py` | ✅ | ✅ |
| `src/scheduling/agent.py` | ✅ | ✅ |
| `src/scheduling/calendar_client.py` | ✅ | ✅ |
| `src/integrations/twilio_client.py` | ✅ | ✅ |
| `src/integrations/notify.py` | ✅ | ✅ |
| `src/data/firestore_client.py` | ✅ | ✅ |
| `src/data/models.py` | ✅ | ✅ |
| `src/tasks/followups.py` | ✅ | ✅ |
| `tests/test_state_machine.py` | ✅ | ✅ |
| `tests/test_scoring.py` | ✅ | ✅ |
| `tests/test_calendar_client.py` | ✅ | ✅ |
| `frontend/lead-form/index.html` | ✅ | ✅ |
| `.env.example` | ✅ | ✅ |
| `README.md` | ✅ | ✅ |
| `pyproject.toml` | ✅ | ✅ |
| `requirements.txt` | ✅ | ✅ |

**Note:** The spec listed `real-estate-real-estate-agent/src/data/firestore_client.py` — this appears to be a typo in the spec. The file exists at the correct path `src/data/firestore_client.py`. ✅

---

## 2. Interface Contracts (spec §6)

### Conversation Agent `src/conversation/agent.py`

**Spec signature:**
```python
def handle_message(lead_id: str, incoming_text: str) -> ConversationResult:
```

**Actual signature:**
```python
def handle_message(
    lead: "Lead",
    messages: list["Message"],
    incoming_text: str,
) -> ConversationResult:
```

❌ **SPEC VIOLATION** — The function accepts a pre-loaded `Lead` object and `messages` list instead of `lead_id: str`. The design is architecturally sound (caller loads the lead, keeping the function testable without Firestore), but it deviates from the exact contract in §6. See `review/issues.md` Issue #1.

### Scheduling Agent `src/scheduling/agent.py`

| Spec signature | Actual | Verdict |
|---------------|--------|---------|
| `find_slots(preferred_window: str \| None) -> list[TimeSlot]` | `find_slots(preferred_window: Optional[str] = None) -> list[TimeSlot]` | ✅ Compliant |
| `book_slot(lead_id: str, slot: TimeSlot) -> Appointment` | `book_slot(lead_id: str, slot: TimeSlot, lead: Lead) -> Appointment` | ⚠️ Extra `lead` param (see Issue #2) |
| `reschedule(lead_id: str, new_slot: TimeSlot) -> Appointment` | `reschedule(lead_id: str, new_slot: TimeSlot, event_id: str) -> Appointment` | ⚠️ Extra `event_id` param (see Issue #2) |
| `cancel(lead_id: str) -> None` | `cancel(lead_id: str, event_id: str) -> None` | ⚠️ Extra `event_id` param (see Issue #2) |

The extra parameters are pragmatically necessary — the spec is incomplete here (it does not specify how event IDs are passed for modifications). This is a spec gap, not a builder error per se.

### Cloud Tasks `src/tasks/followups.py`

| Spec signature | Actual | Verdict |
|---------------|--------|---------|
| `schedule_followup(lead_id: str, delay_hours: int, kind: str) -> None` | Matches exactly | ✅ |
| `cancel_pending_followups(lead_id: str) -> None` | Matches exactly | ✅ |

---

## 3. State Machine Correctness

**File:** `src/coordinator/state_machine.py`

### Pure function check
- ✅ No `import google`, no `genai`, no `requests`, no `open()`, no Firestore, no Twilio
- ✅ Only imports are `from __future__ import annotations`, `typing.TYPE_CHECKING`, and a TYPE_CHECKING-guarded `Lead` (not executed at runtime)
- ✅ Pure deterministic function — no I/O, no LLM calls, no side effects

### States coverage

The spec requires 13 states: NEW, CONTACTED, AWAITING_REPLY, REPLIED, SCORED, SLOT_OFFERED, BOOKED, REMINDED, RESCHEDULE_REQUESTED, CANCELLED, STALE, DONE, plus fallback.

| State | Appears as source in table | Appears as destination | Notes |
|-------|--------------------------|----------------------|-------|
| NEW | ✅ | — | Origin state |
| CONTACTED | ✅ | ✅ | |
| AWAITING_REPLY | ✅ | ✅ | |
| REPLIED | ✅ (special branch) | ✅ | |
| SCORED | ✅ | ✅ | |
| SLOT_OFFERED | ✅ | ✅ | |
| BOOKED | ✅ | ✅ | |
| REMINDED | ✅ | ✅ | |
| RESCHEDULE_REQUESTED | ❌ not a source state | ❌ not a destination | Defined in models.py STATES list but never used in transition table |
| CANCELLED | — | ✅ | Terminal state, correctly falls through to fallback |
| STALE | — | ✅ | Terminal state |
| DONE | — | ✅ | Terminal state |
| Fallback | ✅ | — | `return current, []` |

⚠️ **WARNING** — `RESCHEDULE_REQUESTED` is listed in `models.py`'s `STATES` constant as one of the 13 states, but it never appears as a source or destination in the transition table. Reschedule events are handled by transitioning directly from `BOOKED`/`SLOT_OFFERED` to `SLOT_OFFERED`. The state effectively exists only on paper. See Issue #3.

### Transition table — all 12 explicit transitions verified:
1. `(NEW, lead_created)` → `CONTACTED` ✅
2. `(CONTACTED, inbound_message)` → `REPLIED` ✅
3. `(AWAITING_REPLY, inbound_message)` → `REPLIED` ✅
4. `(AWAITING_REPLY, timer_24h)` → `AWAITING_REPLY` (nudge) ✅
5. `(AWAITING_REPLY, timer_72h)` → `STALE` ✅
6. `(REPLIED, is_complete_true)` → `SCORED` (if payload complete) ✅
7. `(REPLIED, is_complete_true)` → `AWAITING_REPLY` (if not complete) ✅
8. `(SCORED, scored)` → `SLOT_OFFERED` ✅
9. `(SLOT_OFFERED, slot_confirmed)` → `BOOKED` ✅
10. `(BOOKED, timer_reminder)` → `REMINDED` ✅
11. `(BOOKED, cancel_requested)` → `CANCELLED` ✅
12. `(BOOKED, reschedule_requested)` → `SLOT_OFFERED` ✅
13. `(SLOT_OFFERED, reschedule_requested)` → `SLOT_OFFERED` ✅
14. `(REMINDED, meeting_done)` → `DONE` ✅

---

## 4. JSON Output Contracts

### `src/conversation/agent.py`
- ✅ `_strip_fences()` function present, strips ` ```json ` and ` ``` ` before `json.loads`
- ✅ `json.loads(raw)` called on stripped text
- ✅ Returns all required fields: `reply_text`, `extracted`, `intent`, `is_complete`, wrapping in `ConversationResult`
- ✅ `GEMINI_API_KEY` guard raises `EnvironmentError` with descriptive message

### `src/scheduling/agent.py`
- ✅ `_strip_fences()` present and applied before `json.loads`
- ✅ `GEMINI_API_KEY` guard raises `EnvironmentError`
- ✅ Returns `message_text` from JSON, falls back gracefully

### `src/coordinator/agent.py`
- ✅ `_strip_fences()` present
- ✅ `GEMINI_API_KEY` guard raises `EnvironmentError`

### `src/conversation/scoring.py`
- ✅ `_strip_fences()` present
- ✅ `GEMINI_API_KEY` guard raises `EnvironmentError`

---

## 5. Lead Scoring (`src/conversation/scoring.py`)

### Rule-based tier determination
```python
def _rule_based_score(lead: "Lead") -> str:
    has_budget = bool(lead.budget)
    has_availability = bool(lead.availability)
    has_prefs = bool(lead.property_preferences)

    if has_budget and has_availability:
        return "HIGH"
    if has_budget or (has_prefs and has_availability):
        return "MEDIUM"
    return "LOW"
```

- ✅ HIGH/MEDIUM/LOW logic is rule-based, NOT delegated to the LLM
- ✅ Gemini is only used to generate the `reason` sentence, not to determine the tier
- ✅ Rubric matches spec: HIGH = budget + timeline, MEDIUM = budget OR prefs+availability, LOW = neither
- ✅ Graceful fallback if Gemini call fails (returns default reason sentence)

---

## 6. Data Model Completeness (`src/data/models.py`)

### Lead fields
| Field (spec) | Field (actual) | Verdict |
|-------------|---------------|---------|
| leadId | lead_id | ✅ (Python snake_case convention) |
| phone | phone | ✅ |
| name | name | ✅ |
| state | state | ✅ |
| budget | budget | ✅ |
| propertyPreferences | property_preferences | ✅ |
| availability | availability | ✅ |
| score | score | ✅ |
| scoreReason | score_reason | ✅ |
| createdAt | created_at | ✅ |
| lastReplyAt | last_reply_at | ✅ |
| followupsSent | followups_sent | ✅ |
| appointment | appointment | ✅ |
| salespersonAlerted | salesperson_alerted | ✅ |

### Other models
| Model | Required fields | Verdict |
|-------|----------------|---------|
| Appointment | event_id, lead_id, start, end | ✅ All present |
| Message | message_id, lead_id, direction, body, timestamp | ✅ All present |
| TimeSlot | start, end | ✅ |
| ConversationResult | reply_text, extracted, intent, score, is_complete | ✅ All present |
| CoordinatorDecision | action, next_state, reasoning, escalate | ✅ All present |

---

## 7. Tests

### `tests/test_state_machine.py` — 19 test cases
- ✅ Covers all 14 explicit transitions (14 happy path tests)
- ✅ Covers invalid/terminal state cases: DONE, STALE, NEW (no inbound rule), CANCELLED, unknown event (5 tests)
- ✅ Well above the minimum 12 test cases requirement

### `tests/test_scoring.py` — 9 test cases
- ✅ Tests HIGH case (budget + availability) with mocked Gemini
- ✅ Tests MEDIUM cases (budget only, prefs+availability)
- ✅ Tests LOW cases (no info, prefs only)
- ✅ Tests fallback when GEMINI_API_KEY not set
- ✅ Gemini properly mocked via `patch.dict("sys.modules", ...)`

### `tests/test_calendar_client.py` — 6 test cases
- ✅ `get_free_slots`: empty calendar, busy periods skipped, fully busy, returns TimeSlot objects
- ✅ `create_event`: returns Appointment with correct fields, calls correct calendar ID
- ✅ Google API properly mocked with `MagicMock`

---

## 8. Cross-Stream Import Pollution

| Check | Result |
|-------|--------|
| `state_machine.py` imports from `conversation/` | ✅ None (string literals only) |
| `state_machine.py` imports from `scheduling/` | ✅ None |
| `conversation/` imports from `scheduling/` | ✅ None |
| `scheduling/` imports from `conversation/` | ✅ None |
| Circular imports | ✅ None detected |

The coordinator (`agent.py`) imports from all streams — this is correct and expected. All cross-stream calls are deferred imports inside function bodies, preventing circular import errors at module load time.

---

## 9. `.env.example` Completeness

| Required variable (spec) | Present | Notes |
|--------------------------|---------|-------|
| GOOGLE_CLOUD_PROJECT | ✅ | |
| GOOGLE_APPLICATION_CREDENTIALS | ✅ | |
| GEMINI_API_KEY | ✅ | |
| TWILIO_ACCOUNT_SID | ✅ | |
| TWILIO_AUTH_TOKEN | ✅ | |
| TWILIO_WHATSAPP_FROM | ✅ | |
| SALESPERSON_EMAIL | ✅ | |
| CALENDAR_ID | ✅ | |
| CLOUD_TASKS_QUEUE | ✅ | |
| CLOUD_RUN_URL | ✅ | |

✅ All 10 required variables present. Additional helpful variables also included (SMTP fallback, SendGrid, FROM_EMAIL, CLOUD_TASKS_LOCATION).

---

## 10. README Quality

| Required section | Present | Quality |
|-----------------|---------|---------|
| Project summary | ✅ | Clear one-paragraph description |
| Architecture overview | ✅ | Describes all agents, state flow, and integrations |
| Prerequisites | ✅ | Lists GCP APIs, service account, Gemini key, Twilio, Python version |
| Local setup | ✅ | Step-by-step with venv, install, env config, uvicorn |
| Twilio sandbox instructions | ✅ | Steps to join sandbox, webhook URL, env var |
| Cloud Run deployment | ✅ | gcloud commands for build and deploy |
| Running tests | ✅ | `pytest tests/ -v` with coverage description |
| Known limitations (Twilio sandbox tradeoff) | ✅ | Explicitly mentions shared number and Meta approval requirement |

✅ README meets all quality requirements.

---

## 11. Git Hygiene Note

The builder agent created all files but made **zero git commits** — the repository has an empty git history (`fatal: your current branch 'master' does not have any commits yet`). All work exists only as untracked files. This is unusual and means there are no intermediate commit checkpoints to review. The final state of the code is complete and reviewable, but the incremental commit history the spec anticipated does not exist.

---

## Summary

### ✅ Passed Checks
1. All 22 required files present and non-empty
2. `state_machine.py` is a pure function — no LLM, no I/O, no side effects
3. All 14 state machine transitions correctly implemented (13+ table entries + fallback)
4. Markdown fence stripping (`_strip_fences`) implemented in all 4 Gemini call sites
5. `GEMINI_API_KEY` guard raises `EnvironmentError` in all Gemini-calling modules
6. Lead scoring is rule-based (not LLM-delegated); Gemini generates reason only
7. All data models complete with all required fields (camelCase → snake_case convention)
8. Test coverage: 19 state machine tests, 9 scoring tests, 6 calendar tests
9. No cross-stream import pollution between conversation/scheduling/coordinator streams
10. `.env.example` contains all 10 required variables plus extras
11. README covers all 8 required sections with good quality

### ⚠️ Warnings
1. **`RESCHEDULE_REQUESTED` state unreachable** — listed in `STATES` constant but never entered in the transition table. Reschedule is handled as an event, not a persistent state. (Issue #3)
2. **`book_slot`, `reschedule`, `cancel` have extra parameters** — pragmatically necessary due to spec incompleteness (spec does not specify how `event_id` flows through). (Issue #2)
3. **No git commits** — the builder produced no commit history; all files exist only as untracked working tree changes.
4. **No Dockerfile** — README itself acknowledges this as a known limitation.

### ❌ Spec Violations
1. **`handle_message` signature deviates from spec §6** — spec requires `(lead_id: str, incoming_text: str)`, actual is `(lead: Lead, messages: list[Message], incoming_text: str)`. The design is architecturally better (testable without Firestore) but breaks the literal contract. (Issue #1)

---

## Overall Assessment

**CONDITIONAL PASS.** The builder has produced a well-architected, functionally complete system. All core spec requirements are met: pure state machine, fence-stripping at all JSON parse sites, rule-based scoring, complete data models, comprehensive test coverage (34 tests total), and clean separation of concerns with no circular imports. The single spec violation (`handle_message` signature) is a deliberate architectural improvement over the spec's naive signature and does not indicate a design flaw — it should be discussed with the spec owner for a formal waiver or a thin wrapper added to comply literally. The `RESCHEDULE_REQUESTED` state ambiguity should be clarified in a follow-up spec revision.
