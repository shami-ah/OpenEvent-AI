# OpenEvent-AI: The Autonomous Venue Booking Engine

OpenEvent-AI is a sophisticated, full-stack system designed to automate the end-to-end venue booking flow for "The Atelier". It combines the flexibility of Large Language Models (LLMs) with the reliability of deterministic state machines to handle inquiries, negotiate offers, and confirm bookings with "Human-In-The-Loop" (HIL) oversight.
development: https://github.com/shami-ah/OpenEvent-AI/tree/main
backend deployment: https://github.com/shami-ah/OpenEvent-AI/tree/integration/hostinger-backend
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
│   ├── adapters/           # Interface adapters (Calendar, GUI)
│   ├── api/                # FastAPI endpoints
│   ├── main.py             # App entry point
│   ├── workflow_email.py   # Core State Machine Orchestrator
│   └── workflows/          # Business Logic
│       ├── groups/         # Step implementations (intake, offer, etc.)
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
```bash
# From project root - create virtual environment (optional but recommended)
python -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements-dev.txt

# Option A: Use the dev server script (RECOMMENDED)
# Automatically handles port cleanup, PID tracking, and API key loading
./scripts/dev/dev_server.sh

# Option B: Use the environment script + manual uvicorn
source scripts/dev/oe_env.sh
uvicorn backend.main:app --reload --port 8000

# Option C: Fully manual setup
export PYTHONPATH=$(pwd)
export OPENAI_API_KEY=your_api_key_here
uvicorn backend.main:app --reload --port 8000
```

**Dev Server Script Commands:**
```bash
./scripts/dev/dev_server.sh         # Start backend (with auto-cleanup)
./scripts/dev/dev_server.sh stop    # Stop backend
./scripts/dev/dev_server.sh restart # Restart backend
./scripts/dev/dev_server.sh status  # Check if backend is running
./scripts/dev/dev_server.sh cleanup # Kill all dev processes (backend + frontend)
```

**Storing API Key in macOS Keychain (optional):**
```bash
# Add key to Keychain (one-time setup)
security add-generic-password -a "$USER" -s 'openevent-api-test-key' -w 'sk-your-key-here'

# Both dev_server.sh and oe_env.sh will auto-load it
```

### 2. Setup Frontend
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
pytest backend/tests/flow/test_happy_path_step1_to_4.py
```

---

## 🛠 Current Status & Configuration

### Recent Updates
- **Supabase Integration**: Can be toggled via `OE_INTEGRATION_MODE=supabase`.
- **Site Visit Logic**: Dedicated sub-flow for handling venue tours.
- **Deposit Configuration**: Managers can now set global deposit rules.
- **HIL Toggle for AI Replies**: Optional review of all AI-generated responses before sending.

### Configuration
Key environment variables (create a `.env` file):

| Variable | Default | Description |
|----------|---------|-------------|
| `OPENAI_API_KEY` | (required) | API key for NLU and Verbalizer |
| `OE_INTEGRATION_MODE` | `json` | `json` (local files) or `supabase` (production) |
| `OE_HIL_ALL_LLM_REPLIES` | `false` | Require approval for ALL AI responses (see below) |
| `OE_DEV_TEST_MODE` | `true` | Enable dev test mode (continue/reset choice) |
| `WF_DEBUG_STATE` | `0` | Set to `1` for verbose workflow logging |
| `VERBALIZER_TONE` | `professional` | Message tone: `professional` or `plain` |

### LLM Provider Settings

The system supports multiple LLM providers with per-operation granularity:

| Variable | Options | Default | Description |
|----------|---------|---------|-------------|
| `AGENT_MODE` | `openai`, `gemini`, `stub` | `openai` | Main LLM provider mode |
| `PROVIDER` | `openai`, `gemini` | `openai` | Provider registry selection |
| `INTENT_PROVIDER` | `openai`, `gemini` | (AGENT_MODE) | Intent classification provider |
| `ENTITY_PROVIDER` | `openai`, `gemini` | (AGENT_MODE) | Entity extraction provider |
| `VERBALIZER_PROVIDER` | `openai`, `gemini` | `openai` | Draft verbalization provider |
| `GOOGLE_API_KEY` | - | (required for Gemini) | Google AI API key |

#### Cost Comparison per API Call

| Operation | OpenAI (o3-mini) | Gemini Flash 2.0 | Savings |
|-----------|------------------|------------------|---------|
| Intent Classification | ~$0.005 | ~$0.00125 | **75%** |
| Entity Extraction | ~$0.008 | ~$0.002 | **75%** |
| Verbalization | ~$0.015 | ~$0.004 | 73% |

#### Cost per Event (Typical Flow)

| Configuration | Cost/Event | Notes |
|---------------|------------|-------|
| Full OpenAI | ~$0.04 | Best quality, highest cost |
| Hybrid (Gemini intent/entity, OpenAI verbal) | ~$0.02 | **Recommended** - 50% savings |
| Full Gemini | ~$0.007 | 82% savings, slightly lower quality |
| Stub mode | $0 | Heuristics only, development/testing |

#### Gemini Free Tier Limits

| Limit | Value | Implication |
|-------|-------|-------------|
| Requests per minute | 15 RPM | ~7.5 messages/minute (2 calls each) |
| Tokens per day | 1,000,000 | More than sufficient for typical use |
| Requests per day | 1,500 | **~750 client messages/day** |

**Calculation:** Each client message = 1 intent call + 1 entity call = 2 API requests.
With 1,500 requests/day limit: `1500 / 2 = 750 messages/day` on free tier.

**To get a Gemini API key:** https://aistudio.google.com/apikey (free, no billing required)

#### Cost Optimization Strategy
- Use `AGENT_MODE=gemini` for intent/entity extraction (75% cheaper than OpenAI)
- Keep `VERBALIZER_PROVIDER=openai` for client-facing message quality
- Use `VERBALIZER_TONE=plain` to disable LLM verbalization entirely (testing only)
- Use `AGENT_MODE=stub` for deterministic heuristics (no LLM cost, lower quality)

#### Admin UI Toggle
- **Global Deposit**: Configure at runtime via admin panel → Deposit Settings
- **LLM Provider**: Configure at runtime via admin panel → LLM Settings

> **📚 Detailed Architecture:** For a complete breakdown of which extraction methods (Regex, NER, LLM) are used where, see [`docs/internal/LLM_EXTRACTION_ARCHITECTURE.md`](docs/internal/LLM_EXTRACTION_ARCHITECTURE.md)

### Dev Test Mode (Continue/Reset Choice)

When testing with an existing event, the system offers a choice to continue at the current step or reset to a new event. This is useful during development to avoid resetting the database between tests.

**What happens:**
- Message matches an existing event AND event is past Step 1
- System returns a choice prompt instead of processing
- "Continue" resumes at current step with all existing data
- "Reset" creates a new event from scratch

**Control the behavior:**
```bash
# Disable dev test mode (always continue automatically)
export OE_DEV_TEST_MODE=false

# Or skip choice programmatically:
curl -X POST http://localhost:8000/api/start-conversation \
  -H "Content-Type: application/json" \
  -d '{"email_body": "...", "client_email": "...", "skip_dev_choice": true}'

# Or use the continue endpoint:
curl -X POST http://localhost:8000/api/client/{client_id}/continue
```

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

## 🎛 Admin Features

### Prompt Configuration & Workflow Editor
A dedicated configuration page is available for non-technical administrators (e.g., Co-Founders, Managers) to safely tune the AI's behavior without touching code.

**Access:**
Navigate to `http://localhost:3000/admin/prompts`

**Capabilities:**
*   **Edit Global Persona:** Modify the "System Prompt" to change the AI's tone, empathy level, or core rules.
*   **Step-Specific Instructions:** Fine-tune the logic and instructions for each of the 7 workflow steps (e.g., "Be more pushy in Step 5").
*   **Safety & History:**
    *   **Persistence:** Changes are only live after pressing "Save".
    *   **Version Control:** Every save creates a timestamped history entry.
    *   **Instant Revert:** You can browse past versions and revert to any previous state with one click, ensuring you can experiment safely.
*   **Lovable Compatible:** The interface is built with standard React/Tailwind components, making it easy to integrate into other Lovable-based tools.

---

## 📚 Documentation
For deeper dives into specific subsystems:
- **[Workflow Rules](docs/guides/workflow_rules.md)**: The "Constitution" of the booking logic.
- **[Architecture Diagrams](docs/reference/ARCHITECTURE_DIAGRAMS.md)**: Visual guide to the system architecture, workflow stages, and detection logic.
- **[Team Guide](docs/guides/TEAM_GUIDE.md)**: Best practices and troubleshooting.
- **[Integration Guide](docs/integration/frontend_and_database/guides/INTEGRATION_PREPARATION_GUIDE.md)**: How to deploy and connect to real infrastructure.
- **[Dev Changelog](DEV_CHANGELOG.md)**: Day-by-day summary of new features, fixes, and experiments.
- **[Open Decisions](docs/internal/planning/OPEN_DECISIONS.md)**: Documented architecture choices and the reasoning behind them.
- **[Change Propagation Readme](docs/internal/backend/CHANGE_PROPAGATION_README.md)**: How updates move through the repo and what to touch when.
- **[Implementation Plans](docs/plans/)**: Deep-dive project plans (multi-tenant rollout, detection revamp, calendar integration, etc.).

Docs layout (top-level subfolders):
- `docs/guides/`: Team Guide, Workflow Rules, GPT prompt, Step 4/5 requirements, and other playbooks.
- `docs/manual_ux/`: Deterministic/manual UX transcripts and validation reports.
- `docs/reference/`: Architecture diagrams, dependency graph, and structural maps.
- `docs/integration/frontend_and_database/`: Integration + Supabase contract docs split into `guides/`, `specs/`, `security/`, and `status/`.
- `docs/internal/`: Private notes grouped into `backend/`, `planning/`, `completed/`, and `research/`.
- `docs/plans/`: Roadmaps split into `active/` (in-flight plans) and `completed/` (DONE__ records); `docs/reports/` + `docs/archive/` hold historical reports and backups.

Scripts layout:
- `scripts/dev/`: Local dev helpers (`dev_server.sh`, env setup, run_all, ports utilities).
- `scripts/tests/`: CI and smoke/test lanes (`test-smoke.sh`, `test-all.sh`, regression helpers).
- `scripts/manual_ux/`: Deterministic/manual UX flows and validators.
- `scripts/tools/`: One-off utilities (calendar generation, measurement helpers).
