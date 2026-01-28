# OpenEvent UX Guidelines & Principles

**Last Updated:** January 20, 2026
**Status:** Living Document
**Audience:** Developers, AI Agents, Product Designers

---

## 1. Core Philosophy

The OpenEvent system is designed to balance **safety** (preventing hallucinations) with **hospitality** (providing a warm, seamless client experience).

*   **Safety First:** Never invent prices or availability. All critical data (dates, rooms, costs) must come from the deterministic backend logic.
*   **Hospitality Second:** The interface (email/chat) should feel like a helpful, competent human assistant. Avoid bureaucratic language or exposing internal state.
*   **Flexibility Third:** Users change their minds. The system must support non-linear flows (detours) and vague inquiries without breaking.

---

## 2. The Persona: "The OpenEvent Assistant"

*   **Tone:** Professional, Warm, Competent, Concise.
*   **Role:** An efficient venue coordinator. Not the "Owner" (who makes final decisions), but a trusted aide who handles the logistics.
*   **Voice:**
    *   *Do:* "I've checked our calendar, and..."
    *   *Don't:* "Database query returned 0 results."
    *   *Do:* "Our manager will review this and get back to you shortly."
    *   *Don't:* "State transition to HIL_REVIEW pending."
    *   *Hygiene:* Use standard punctuation (periods, commas). Avoid em-dashes (—) which can feel robotic/AI-generated in excess. Keep paragraphs short (2-3 sentences max).

---

## 3. Communication Guidelines

### A. "Robotic Transparency" (The Black Box Rule)
Clients should **never** see the internal machinery of the workflow.

*   **Footers:** Debug footers (`Step: 4 · State: Waiting on HIL`) are for **internal logs only**. Never append them to client-facing emails.
*   **HIL Decisions:** When a manager approves a task, the response should be seamless.
    *   *Bad:* "Manager decision: Approved. Manager note: Send the contract."
    *   *Good:* "I'm happy to confirm that [Manager Name] has approved your request! I've attached the contract..."
*   **Verbalization:** Use the "Universal Verbalizer" to wrap dry data (lists, dates) in warm, conversational text.

### B. "Frankenstein" Emails (Proposal Delivery)
Avoid pasting complex data tables directly into chat/email bodies.

*   **Gold Standard:** Brief, warm email body + **Link to Web Proposal** (or PDF attachment).
*   **Structure:**
    *   *Greeting & Warm Intro:* "Here is the proposal we discussed..."
    *   *High-Level Summary:* "It covers the main room for 50 guests on [Date]."
    *   *Call to Action:* "Click here to view the full details and pricing."
    *   *Closing:* "Let me know if you have questions."
*   **Chat Tables:** **PROHIBITED.** Do not render Markdown tables in chat bubbles; they break on mobile. Use conversational summaries or list views.

---

## 4. Key Workflow Patterns

### A. The "Safety Sandwich"
Used to prevent hallucinations.
1.  **Top Bun:** User intent is classified (NLU).
2.  **Meat:** Python logic calculates exact prices/availability (Deterministic).
3.  **Bottom Bun:** LLM generates the final message *using only the data from the Meat layer*.

### B. Intelligent Detours
Users are non-linear.
*   If a user is at Step 4 (Offer) but asks to change the date, the system **must** detour to Step 2 (Date Confirmation), resolve the change, and then intuitively return to the Offer context or a logical resting place.
*   *Principle:* Never say "I can't do that right now." Instead, say "Let's check that date for you" and handle the state transition in the background.
*   *Explicit Updates:* When a detour changes a critical value (e.g., Room A -> Room B due to availability), the system must explicitly state: *"Room A is no longer available on [New Date]. For your event with [X] guests, I recommend Room B..."*

### C. The "Rate Card" Logic (Soft Gates)
Avoid "Computer Says No" blocks on early-stage inquiries.
*   **Scenario:** User asks "How much are your rooms?" without a date.
*   **Old Logic:** "I need a date first." (Blocker)
*   **New UX Rule:** Treat as **General Q&A**. Provide a **broad price range** (e.g., "$500–$1500") and *then* invite them to check specific dates. "Ballpark figures" are valid conversation starters.

---

## 5. Specific Flow UX Decisions

### A. Room Availability Display
When a user asks "What's free in February?", prioritize **information density** to allow quick qualification.

*   **Format:** **Rich Summary Bullet Points**
    *   *Pattern:* `- **[Room Name]**: [Capacity] guests; [Key Feature] — [Dates]`
    *   *Example:* "- **Room A**: 50 guests; Projector — 15.02, 22.02"
*   **Why:** Capacity is the primary dealbreaker. Seeing it inline saves a click.
*   **Display Logic (Miller's Law):**
    *   **Count <= 8:** Show **ALL** rooms. Do not truncate.
    *   **Count > 8:** Show **Top 6** matches + "and X more options available".

### B. Billing Address Collection
Don't let administration kill conversion.

*   **Pattern:** **Gate at Confirmation (Step 7) - "The Amazon Model"**
*   **Rule:** Do *not* block the initial Offer (Step 4) on having a full billing address.
*   **Flow:**
    1.  Generate Offer with available info (e.g., just "Acme Corp" or name).
    2.  Let client browse and negotiate.
    3.  When client says **"I accept"**, *then* check for full billing details.
    4.  If incomplete: "Great! To generate the final contract, I just need your street address and postal code."

### C. Human-in-the-Loop (HIL)
Managers are pilots, not just rubber stamps.

*   **Modes:**
    *   **Autonomous (Toggle OFF):** System sends Offers (Step 4) directly to client. Manager only reviews at Step 7 (Final Confirmation) or for special requests.
    *   **Supervised (Toggle ON):** Manager reviews **ALL** AI replies, including Offers.
*   **Context is King:** HIL dashboards must show **Conversation History** and **Client Preferences**, not just the draft message.
*   **Edit & Send:** Managers must be able to **edit** the AI's draft before sending. The UI must promote this capability.

### D. Site Visits
*   **2-Step Flow:** Never auto-select a time slot.
    1.  **Step 1:** Offer available Dates (e.g., "Mon 12th, Wed 14th").
    2.  **Step 2:** Once date picked, offer Time Slots (e.g., "10:00 or 14:00?").
*   **Conflict Handling:** If a requested date is blocked, offer specific alternatives, don't just say "unavailable."

---

## 6. Detailed UX Specifications & Limits

### Display Limits
*   **Room List:** Max **8** items full display. Truncate after **6** if total > 8.
*   **Catering Teaser:** Show max **3** popular items in Step 3 if catering not mentioned.
*   **Counter Proposals:** Limit client to **3** counter-offers before escalating to HIL (prevents infinite negotiation loops).
*   **Q&A Results:** Format as **paragraphs** with blank lines, NOT bullet points (cleaner in chat).

### System Limits
*   **Upload Size:** Max **10MB** per file.
*   **Rate Limiting:** **10 requests/second** per IP (`RATE_LIMIT_RPS=10`).
*   **Retention:** Client memory history capped at **50 messages** to maintain relevance.

### Formatting Rules
*   **Dates:** Always format as `DD.MM.YYYY` (e.g., `15.03.2026`) in text. ISO (`YYYY-MM-DD`) strictly for DB/API.
*   **Currency:** `CHF 1,200.00` (Space separator, 2 decimals).
*   **Paragraphs:** Split long text blocks. Max 3 sentences per paragraph. Double newline (`\n\n`) between paragraphs.

---

## 7. Implementation Status Reference

| Feature | Status | Implementation Note |
| :--- | :--- | :--- |
| **Safety Sandwich** | ✅ Implemented | Core architecture in `workflow_email.py` |
| **Intelligent Detours** | ✅ Implemented | `change_propagation.py` handles redirects |
| **Audit Trail** | ✅ Implemented | All steps logged with `audit_label` |
| **HIL Editing** | ✅ Implemented | Backend supports `edited_message` param |
| **"Amazon" Billing Gate**| ✅ Implemented | Gated at Step 7, skipped at Step 4 |
| **Rich Room List** | ✅ Implemented | `general_qna.py` uses 8/6 limit logic |
| **2-Step Site Visit** | ✅ Implemented | `site_visit_handler.py` separates date/time |
| **Rate Card Logic** | ⚠️ Planned | Needs config in `General Q&A` module |
| **Web-Based Proposal**| ⚠️ Planned | Currently embedding Markdown tables (Legacy) |
| **Hidden Footers** | ⚠️ Planned | Debug footers still visible in some outputs |

---

## 8. Developer Checklist (New Features)

When adding a new feature or flow, ask:
1.  **Is it safe?** (Does it rely on deterministic data?)
2.  **Is it hospitable?** (Does it sound like a helpful human? No "robots".)
3.  **Is it flexible?** (Can the user change their mind?)
4.  **Is it opaque?** (Are internal states hidden from the client?)
5.  **Does it respect limits?** (Is it mobile-friendly? No huge tables?)

---

## 9. Evolution of UX Rules (Legacy vs Current)

Tracking how our design principles have evolved helps understanding *why* certain decisions were made.

| UX Aspect | Legacy / Deprecated Rule | Current Rule (2026) | Reason for Change |
| :--- | :--- | :--- | :--- |
| **Display Limits** | Show Top 3, summarize rest | **Show Top 8, truncate after 6** | Boutique venues have small inventories (<10). Hiding inventory ("+5 more") hurts discovery. Miller's Law (7±2) allows for denser lists. |
| **Q&A Format** | Bulleted lists (`- Item`) | **Paragraphs** | Bullets cluttered the chat UI vertically. Paragraphs feel more natural and conversational. |
| **Billing** | "Gate before Offer" | **"Gate at Confirmation"** | Prioritizing conversion. Asking for addresses before showing a price felt bureaucratic and increased drop-off. |
| **Room Details** | Minimal (`Room A available`) | **Rich Summary** (`Room A: 50pax...`) | Capacity is the primary qualifier. Hiding it forced users to click/ask "how big is it?", adding friction. |
| **Catering** | Explicit Prompt ("Do you want food?") | **Teaser / Passive** | Blocking the flow to ask about food felt nagging. A passive "teaser" in Step 3 is less intrusive. |
| **Tables** | Embedded Markdown tables | **Info Pages / Links** | Markdown tables break on mobile screens. Complex data belongs in a dedicated view, not the chat stream. |

---

## 10. Error Handling & Fallbacks (Dev vs. Prod)

How the system behaves when it breaks is a critical part of UX.

### Philosophy: "No Legacy Defaults"
There is no such thing as "Legacy Mode" for new features. Code is either **Current** or **Broken**. Do not silently fall back to deprecated logic (e.g., regex extraction) if the modern logic (e.g., Unified LLM) fails.

### Environment-Specific Behavior

| Scenario | **Development (ENV=dev)** | **Production (ENV=prod)** |
| :--- | :--- | :--- |
| **Goal** | **Loud Failure.** Expose bugs immediately. | **Graceful Recovery.** Preserve the relationship. |
| **API Error** | Show `[ERROR: OpenAI Rate Limit]` in chat. | **Log Only.** Alert manager via HIL. Do not show error code to client. |
| **Unknown Intent**| Show `[FALLBACK: Intent Classification Failed]` | Route to **HIL** (Manual Review). Message: *"I've passed your request to our team..."* |
| **Action** | **Explicit Error Message** | **No Action** (Silence) or Safe HIL Handoff. |

**Rule:** Never send a robotic "I don't understand" or "System Error" message to a client in Production. If the AI is unsure, it remains silent or escalates to a human.
