# Spec Violations — GitHub-Style Issues

---

## ISSUE #1 — `handle_message` signature does not match spec §6

**Severity:** Spec Violation  
**File:** `src/conversation/agent.py`  
**Status:** Open

### Expected (spec §6)
```python
def handle_message(lead_id: str, incoming_text: str) -> ConversationResult:
```

### Actual
```python
def handle_message(
    lead: "Lead",
    messages: list["Message"],
    incoming_text: str,
) -> ConversationResult:
```

### Impact
The spec requires `lead_id: str` as the first parameter, implying the function is responsible for loading the lead and its history from the data layer. The implementation instead accepts a pre-loaded `Lead` object and a `messages` list as caller-supplied arguments. This is a valid design choice (it decouples the function from Firestore), but it breaks the exact interface contract in the spec.

**Resolution options:**
1. Accept `lead_id: str` and load from Firestore internally (spec-compliant).
2. Keep current signature but document the deviation as an intentional design decision.

---

## ISSUE #2 — `book_slot` and `cancel` and `reschedule` have extra parameters not in spec §6

**Severity:** Spec Violation (minor)  
**File:** `src/scheduling/agent.py`  
**Status:** Open

### Expected (spec §6)
```python
def book_slot(lead_id: str, slot: TimeSlot) -> Appointment
def reschedule(lead_id: str, new_slot: TimeSlot) -> Appointment
def cancel(lead_id: str) -> None
```

### Actual
```python
def book_slot(lead_id: str, slot: TimeSlot, lead: Lead) -> Appointment
def reschedule(lead_id: str, new_slot: TimeSlot, event_id: str) -> Appointment
def cancel(lead_id: str, event_id: str) -> None
```

### Impact
`book_slot` adds a `lead: Lead` parameter (needed to create the calendar event); `reschedule` and `cancel` add `event_id: str` (needed to call the Calendar API). These are pragmatic additions that make the implementation functional, but they deviate from the spec signatures. The spec is incomplete (it does not account for how `event_id` is passed), so the builder compensated.

---

## ISSUE #3 — `RESCHEDULE_REQUESTED` state is defined in `models.py` but never appears as a source state in the transition table

**Severity:** Warning (potential spec gap)  
**File:** `src/coordinator/state_machine.py`, `src/data/models.py`  
**Status:** Open

### Detail
`models.py` lists `RESCHEDULE_REQUESTED` as one of the 13 states in `STATES`. The spec mentions 13 states including `RESCHEDULE_REQUESTED`. However, the transition table handles reschedule events via `("BOOKED", "reschedule_requested")` and `("SLOT_OFFERED", "reschedule_requested")` — both transition directly back to `SLOT_OFFERED`. The `RESCHEDULE_REQUESTED` state is never entered as a destination or used as a source; it exists in the constant list but is effectively unreachable.

**Resolution:** Either add a transition `("RESCHEDULE_REQUESTED", ...)` in the table, or clarify with the spec owner whether `RESCHEDULE_REQUESTED` is a transient signal (event) rather than a persistent state.

---

## ISSUE #4 — `src/data/firestore_client.py` is at the wrong path in spec listing

**Severity:** Minor (spec listing typo, not a code issue)  
**File:** N/A  
**Status:** Informational

### Detail
The spec §1 repo structure check lists the path as:
```
real-estate-real-estate-agent/src/data/firestore_client.py
```
This appears to be a typo (doubled `real-estate-`). The actual file exists at the correct path:
```
real-estate-agent/src/data/firestore_client.py
```
No action needed on the builder side.

---

## ISSUE #5 — `handle_message` does not handle `lead_id` not-set / GEMINI_API_KEY guard only in helper

**Severity:** Minor  
**File:** `src/conversation/agent.py`  
**Status:** Open

### Detail
The `GEMINI_API_KEY` guard is correctly placed in `_get_gemini_model()` which raises `EnvironmentError`. However the spec says the function should handle the key not being set. The implementation does handle this correctly via the helper — this is a style concern only.
