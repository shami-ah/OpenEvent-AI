# OpenEvent-AI: The Autonomous Venue Booking Engine

OpenEvent-AI is a sophisticated, full-stack system designed to automate the end-to-end venue booking flow for "The Atelier". It combines the flexibility of Large Language Models (LLMs) with the reliability of deterministic state machines to handle inquiries, negotiate offers, and confirm bookings with "Human-In-The-Loop" (HIL) oversight.

> **Branch focus:** `integration/hostinger-backend` ships only the backend API that is deployed to Hostinger. Frontend apps live in the repo but are not part of this deployment target.

## 🚀 Overview

The system ingests client inquiries (currently simulated via chat), maintains a deterministic event record, and coordinates every step of the booking process. Unlike simple chatbots, OpenEvent-AI is built on a **workflow engine** that tracks the lifecycle of an event from a "Lead" to a "Confirmed" booking.

### Key Features
- **Deterministic Workflow**: A 7-step state machine ensures no inquiry is lost and every booking follows the strict business rules.
- **Hybrid AI/Logic**: Uses LLMs for Natural Language Understanding (NLU) and drafting responses, but relies on rigid Python logic for pricing, availability, and state transitions.
- **"Safety Sandwich"**: A unique architectural pattern where LLM outputs are "sandwiched" between deterministic fact-extraction and verification layers to prevent hallucinations (e.g., inventing prices or rooms).
- **Human-In-The-Loop (HIL)**: Critical actions (sending offers, confirming dates) generate "Tasks" that require manager approval before proceeding.
- **Seamless Detours**: Clients can change their minds (e.g., "Actually, I need a bigger room") at any point, and the system intelligently "detours" to the previous necessary step without losing context.

---

## 🏗 Architecture

The system is composed of two main applications:

![System Context](docs/assets/diagrams/system_context.png)

### 1. Frontend (`atelier-ai-frontend/`)
A **Next.js 15** application that serves as the user interface for:
- **Clients**: To chat with the AI assistant.
- **Managers**: To review HIL tasks, configure global settings (deposits, pricing), and monitor active events.

### 2. Backend (`backend/`)
A **Python FastAPI** application that acts as the brain. It exposes endpoints for the frontend and hosts the `workflow_email.py` orchestrator.

- **Orchestrator (`backend/workflow_email.py`)**: The central nervous system. It receives messages, loads state, executes the current step's logic, and persists the result.
- **Groups (`backend/workflows/groups/`)**: Logic is divided into "Groups" corresponding to workflow steps (e.g., `intake`, `room_availability`, `offer`).
- **NLU/Detectors (`backend/workflows/nlu/`)**: Specialized modules that analyze text to detect intents (e.g., `site_visit_detector`, `general_qna_classifier`).

---

## 🕵️ Detectors & Cost Efficiency

The system avoids "always-on" LLM calls by using a tiered detection architecture. Cheap, fast methods (Regex/Keywords) run first; expensive LLMs run only when necessary.

### 1. Intent Classifier (The Main Router)
*   **Purpose:** Decides if a message is an event request, a confirmation, or a question.
*   **Mechanism:**
    1.  **Gibberish Gate (Regex):** Immediately catches keyboard mashing ("asdfghjkl"). **Cost: $0**.
    2.  **Resume Check (Keywords):** Detects simple confirmations ("yes", "ok", "proceed"). **Cost: $0**.
    3.  **LLM Classifier:** Only runs if previous checks fail. Uses a specialized prompt to categorize intent.

### 2. General Q&A Classifier
*   **Purpose:** Detects vague availability questions (e.g., "What do you have free in March?").
*   **Mechanism:**
    1.  **Quick Scan (Regex):** Checks for question marks, month names, and "availability" keywords.
    2.  **LLM Extractor:** Only fires if the scan finds potential constraints (e.g., "March", "30 people") that need structured extraction.
*   **Efficiency:** Questions like "Do you have parking?" are caught by keywords and routed to the FAQ module without an extraction LLM call.

### 3. Change & Detour Detector
*   **Purpose:** Detects when a user wants to change a previously agreed variable (Date, Room, Requirements).
*   **Mechanism:** **Dual-Condition Logic**. A change is only triggered if **BOTH** are present:
    1.  **Revision Signal:** A verb like "change", "switch", "actually", "instead".
    2.  **Bound Target:** A reference to a variable ("date", "room") or a specific value ("2025-05-20").
*   **Efficiency:** Prevents false positives. A message like "What dates are free?" (Question) is not mistaken for "Change date" (Action).

### 4. Nonsense / Off-Topic Gate
*   **Purpose:** Silently ignores irrelevant messages to save costs and avoid confusing users.
*   **Mechanism:**
    1.  **Signal Check:** Scans for *any* workflow-relevant keyword (dates, numbers, "booking").
    2.  **Confidence Check:** If no signal is found and the LLM confidence is < 15%, the message is silently ignored.
*   **Cost:** **$0**. Uses existing confidence scores; no new LLM call.

### 5. Safety Sandwich (Hallucination Detector)
*   **Purpose:** Ensures the LLM doesn't invent prices or facts.
*   **Mechanism:**
    1.  **Deterministic Input:** Python calculates the exact price list.
    2.  **LLM Generation:** The AI writes the email body.
    3.  **Regex Verification:** The system scans the output. If the prices/dates don't match the input, it forces a retry or falls back to a template.

---

## 🧠 Core Concepts

### The 7-Step Workflow
1.  **Intake**: Classify intent, capture contact info, and understand requirements.
2.  **Date Confirmation**: Propose and lock in a specific date.
3.  **Room Availability**: Check inventory, handle conflicts, and select a room.
4.  **Offer**: Generate a priced offer (PDF/Text) with deposits and policies.
5.  **Negotiation**: Handle counter-offers and questions.
6.  **Transition**: Final prerequisites check.
7.  **Confirmation**: Payment processing and final booking confirmation.

### Entry & Hash Guards
- **Entry Guards**: Each step has strict entry requirements (e.g., "You cannot enter Step 3 without a confirmed date in Step 2").
- **Hash Guards**: To save compute and API costs, steps calculate a "requirements hash". If the user's input hasn't changed the requirements, the expensive availability calculation is skipped.

---

## 📂 Project Structure

```text
/
├── atelier-ai-frontend/    # Next.js Frontend application
├── backend/                # Python Backend application
│   ├── api/                # FastAPI endpoints
│   ├── main.py             # App entry point
│   ├── workflow_email.py   # Core State Machine Orchestrator
│   └── workflows/          # Business Logic
│       ├── groups/         # Ste
p implementations (intake, offer, etc.)
│       ├── nlu/            # Detectors & Classifiers (Regex + LLM)
│       └── io/             # Database & Task Management
├── docs/                   # Detailed documentation & rules
└── tests/                  # Pytest suite
```

---

## 🚦 Getting Started

### Prerequisites
- **Python 3.10+**
- **Node.js 18+**
- **OpenAI API Key** (Set as `OPENAI_API_KEY` env var)

### 1. Setup Backend

1. **Create a virtual environment (optional, but recommended)**
   ```bash
   python -m venv venv
   source venv/bin/activate
   ```
2. **Install the runtime dependencies (works on any shell/IDE)**
   ```bash
   pip install fastapi uvicorn pydantic python-dotenv openai openai-agents openai-chatkit
   ```
   (or simply `pip install -r requirements-dev` to match the Hostinger runtime snapshot)
3. **(Optional) Install test tooling**
   ```bash
   pip install -r requirements-dev.txt
   ```
   `requirements-dev.txt` only contains pytest/freezegun/etc. for regression suites; skip it if you just need the API running.
4. **Start the backend**
   ```bash
   # macOS shortcut: also sets PYTHONPATH before launching uvicorn
   source scripts/oe_env.sh && uvicorn backend.main:app --reload --port 8000

   # or do it manually on any platform
   export PYTHONPATH=$(pwd)
   uvicorn backend.main:app --reload --port 8000
   ```

> ℹ️ Replace the placeholder `OPENAI_API_KEY=sk-your-openai-key` in `.env` with
> your real key (and never commit the real secret). The backend loads this file
> automatically, so once it’s filled in you can run `uvicorn` without extra env
> exports.

### 2. (Optional) Setup Frontend Locally
The Hostinger deployment only runs the backend, but you can still launch the dev UI if needed:
```bash
cd atelier-ai-frontend
npm install
npm run dev
```
The frontend will be available at `http://localhost:3000`.

### 3. Run Tests
The project has a comprehensive regression suite.
```bash
# Run all tests
pytest

# Run specific workflow tests
pytest backend/tests/workflows/test_workflow_v3_alignment.py
```

---

## 🛠 Current Status & Configuration

### Recent Updates
- **Supabase Integration**: Can be toggled via `OE_INTEGRATION_MODE=supabase`.
- **Site Visit Logic**: Dedicated sub-flow for handling venue tours.
- **Deposit Configuration**: Managers can now set global deposit rules.
- **HIL Toggle for AI Replies**: Optional review of all AI-generated responses before sending.

---

## 🚀 Deploying to Hostinger (Backend Only)

This branch is wired for the Hostinger VPS described in `deploy/README.md`. Quick steps:

1. **SSH into the VPS**
   ```bash
   ssh root@72.60.135.183
   ```
2. **Clone / update the repo**
   ```bash
   cd /opt
   git clone https://github.com/YOUR_USERNAME/OpenEvent-AI.git openevent
   cd openevent
   git checkout integration/hostinger-backend
   ```
3. **Run the provisioning script**
   ```bash
   chmod +x deploy/*.sh
   ./deploy/setup-vps.sh
   ```
4. **Edit `/opt/openevent/.env` to add your real secrets (the tracked `.env` ships with placeholders only).**
5. **Restart the service**
   ```bash
   systemctl restart openevent
   systemctl status openevent
   ```
6. **Verify the API**
   ```bash
   curl http://72.60.135.183:8000/api/workflow/health
   ```

For the complete checklist (nginx config, firewall, API smoke tests), see `deploy/README.md` and `deploy/API_TESTS.md`.

### Configuration
Key environment variables (create a `.env` file):

| Variable | Default | Description |
|----------|---------|-------------|
| `OPENAI_API_KEY` | (required) | API key for NLU and Verbalizer |
| `OE_INTEGRATION_MODE` | `json` | `json` (local files) or `supabase` (production) |
| `OE_HIL_ALL_LLM_REPLIES` | `false` | Require approval for ALL AI responses (see below) |
| `WF_DEBUG_STATE` | `0` | Set to `1` for verbose workflow logging |
| `VERBALIZER_TONE` | `professional` | Message tone: `professional` or `plain` |

### HIL Toggle for AI Reply Approval

By default, the system only requires HIL (Human-in-the-Loop) approval for critical actions like sending offers or confirming bookings. However, during MVP testing with customers or when fine-tuning AI responses, you may want to review **every** AI-generated reply before it reaches the client.

**Enable the toggle:**
```bash
# Option 1: Set in .env file
OE_HIL_ALL_LLM_REPLIES=true

# Option 2: Export before starting the backend
export OE_HIL_ALL_LLM_REPLIES=true
uvicorn backend.main:app --reload --port 8000
```

**What happens when enabled:**
- All AI-generated outbound messages create a "AI Reply Approval" task
- Messages appear in a dedicated queue in the Manager UI
- The manager can approve (send as-is), edit, or reject the response
- Messages are NOT sent to clients until explicitly approved

**When to use:**
- **Development**: Testing new prompt templates or LLM configurations
- **Training**: Reviewing AI quality before going live
- **High-stakes clients**: When extra oversight is needed

**Check current status:**
```bash
curl http://localhost:8000/api/config/hil-status
# Returns: {"hil_all_replies_enabled": true/false}
```

---

## 📚 Documentation
For deeper dives into specific subsystems:
- **[Workflow Rules](docs/workflow_rules.md)**: The "Constitution" of the booking logic.
- **[Architecture Diagrams](docs/ARCHITECTURE_DIAGRAMS.md)**: Visual guide to the system architecture, workflow stages, and detection logic.
- **[Team Guide](docs/TEAM_GUIDE.md)**: Best practices and troubleshooting.
- **[Integration Guide](docs/integration_to_frontend_and_database/INTEGRATION_PREPARATION_GUIDE.md)**: How to deploy and connect to real infrastructure.
- **[Dev Changelog](DEV_CHANGELOG.md)**: Day-by-day summary of new features, fixes, and experiments.
- **[Open Decisions](docs/internal/OPEN_DECISIONS.md)**: Documented architecture choices and the reasoning behind them.
- **[Change Propagation Readme](docs/internal/CHANGE_PROPAGATION_README.md)**: How updates move through the repo and what to touch when.
- **[Implementation Plans](docs/plans/)**: Deep-dive project plans (multi-tenant rollout, detection revamp, calendar integration, etc.).
