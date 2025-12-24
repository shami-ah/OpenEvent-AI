# How it flows now (Date → Room Availability → Reply → GUI)

## TL;DR (what controls what)

- **Mainline runtime:** `backend/main.py` (FastAPI app for chat + GUI buttons)
- **DB + glue:** `backend/workflow_email.py` (reads/writes `events_database.json`)
- **Room Availability step:** `backend/workflows/groups/room_availability` (Orchestrated by workflow engine)
- **Adapters:**
  - `backend/adapters/calendar_adapter.py` (reads busy slots from `backend/adapters/calendar_data/*.json`)
  - `backend/adapters/client_gui_adapter.py` (stub: prints the card we “publish” to the Client GUI)
- **Configs/data:** `backend/rooms.json`, `backend/adapters/calendar_data/`, `backend/events_database.json`

## Prerequisites

- Python 3.10+ (3.9 works, but 3.10+ recommended for `zoneinfo`)
- Node 18+ (Next.js front-end)
- Python deps: `pip install -r requirements.txt` (or at minimum: `fastapi`, `uvicorn`, `pydantic`)
- Front-end deps: `npm install` (run at repo root)
- macOS note: if you hit `.pyc` permission issues, run Python with `-B` or set `PYTHONDONTWRITEBYTECODE=1`.

## Start everything (open 2 terminals)

### Terminal A — Backend API
```bash
# from repo root
export PYTHONDONTWRITEBYTECODE=1   # optional
uvicorn backend.main:app --reload --port 8000
```
Expected log: `INFO:     Application startup complete.`

Alternative (single command): `python3 backend/main.py` (auto-launches the frontend and will try to free port `8000` on startup if a stale process is still listening).

### Terminal B — Frontend (Client + Event Manager UI)
```bash
# from repo root
npm run dev
# UI available at http://localhost:3000
```

## Quick repo layout (for bearings)
```
backend/
  adapters/                  # Calendar, GUI, and other adapters
    calendar_adapter.py      # reads busy slots
    client_gui_adapter.py    # stub for GUI payload
    calendar_data/           # Put busy fixtures here
  main.py                    # FastAPI app (chat + buttons); triggers pipeline after date confirm
  workflow_email.py          # DB helpers for events_database.json
  events_database.json       # persistent store (auto-updated)
  rooms.json                 # Room capacities, buffers, calendar_id
  workflows/                 # Business Logic
    groups/                  # Step implementations (intake, offer, etc.)
```

## End-to-end test (recommended happy path)

1. Open http://localhost:3000 and start a new conversation (acting as the client).
2. Client sends something like:
   ```
   Hello, this is Mark from BrightLabs.
   We'd like to book Room B for ~20 people next month for a training session.
   ```
3. The assistant proposes dates. Client replies with one (`15.03.2025` etc.).
4. Assistant asks: “Please confirm this is your preferred date.”
5. Client replies “yes” (or presses **Confirm date** button).

**What happens automatically:**
- `main.py` detects the confirmation → `_persist_confirmed_date(...)`
- The workflow DB is updated via `workflow_email.py` and an `event_id` is stored on the conversation.
- `main.py` calls `_trigger_room_availability(...)`.
- The availability logic (in `backend/workflows/groups/room_availability`):
  - computes availability (buffers + conflicts + near-miss ±30/60/90 min),
  - drafts the correct reply (Available / Option / Unavailable),
  - prompts in the terminal (`[E]dit / [A]pprove & Publish / [C]ancel`),
  - on **Approve**, prints the GUI card payload (stub) and updates the DB.

You should see in **Terminal A**:
- preview of the drafted reply,
- on approve: `✅ Published to Client GUI.` plus a JSON payload.

And in `backend/events_database.json`:
- `event.event_data["Room Availability"]` (structured),
- `event.event_data["Comms"]["availability_reply"]` (draft/approved/published),
- log entries: `room_availability_assessed`, `availability_reply_drafted`, `availability_reply_published_client_gui`.

## Setting up calendar conflicts (to test each bubble)

Place busy files in `backend/adapters/calendar_data/`, named after each room’s `calendar_id` from `rooms.json`.

**Example 1 — Preferred busy (forces Alternative → Available)**
```
backend/adapters/calendar_data/atelier-room-b.json
{ "busy": [
  {"start":"2025-10-16T13:45:00+02:00","end":"2025-10-16T16:30:00+02:00"}
]}

backend/adapters/calendar_data/atelier-room-a.json
{ "busy": [] }
```
Run the flow → expect **Available** (alternative chosen), status becomes `Availability Assessed`.

**Example 2 — Only near-miss (forces Option)**
Make Room A busy too (overlapping buffers) while keeping B busy.  
Run → expect **Option** with up to 3 bullet suggestions, status `Availability Constraints`.

**Example 3 — No options (forces Unavailable)**
Make A/B/C busy across the whole window ± buffers.  
Run → expect **Unavailable** asking for alternative dates, status `Availability Constraints`.

## Manual run

The standalone `availability_pipeline.py` script is deprecated. To test the flow:

1.  **Use the Dev Server/UI:** Run the full stack and verify the flow in the frontend.
2.  **Run Tests:** Use pytest to run specific flow tests:
    ```bash
    pytest backend/tests/flow/test_room_conflict.py
    ```

## What if Start/End Time is missing?

The pipeline does not crash. It:
- sets `Status = "Needs Clarification"`,
- drafts a polite clarification reply (“Please share start/end time…”),
- saves it as a draft (no CLI approval shown until valid times are present).

## Idempotency (re-confirming the same date)

Confirming the same date again will not re-run availability.  
`main.py` checks the latest `room_availability_assessed` log for the same date and skips rerunning.

## Common issues & fixes

- `.pyc` permission denied (macOS) → run with `python -B` or set `PYTHONDONTWRITEBYTECODE=1`.
- No CLI approval prompt → the pipeline runs **after** the date is confirmed; ensure confirmation happened.
- No conflicts detected → add files under `backend/adapters/calendar_data/<calendar_id>.json`. Missing files mean “free”.
- Wrong date format → the chat uses `DD.MM.YYYY`; system normalizes internally to ISO.

## Next steps in the workflow (after this)

- **Price Model + Catalog Resolver (Offer Draft):** build `event.event_data["Offer Draft"]` from participants/duration + catalog, compute totals.
- **Offer Composer → Human approval → Publish to GUI/Email.**

## One-liner mental model

`main.py` orchestrates the conversation. When the date is confirmed, it calls the availability pipeline, which collects a human approval in the terminal, updates `events_database.json`, and publishes the drafted availability reply to the Client GUI.
