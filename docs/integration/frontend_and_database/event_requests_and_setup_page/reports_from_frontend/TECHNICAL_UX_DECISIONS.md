# Technical & Backend UX Decisions

**Date:** January 12, 2026
**Purpose:** Collection of technical and backend decisions that impact UX but are not directly frontend implementation
**Audience:** Technical team, product owner

---

## Decisions Already Made

### 1. Deposit Reminder Messages
- **Decision:** Use static templates (not AI-generated)
- **Rationale:** Transactional message, cost savings at scale

### 2. Deposit Display in Offers
- **Decision:** Separate "Payment Terms" section at bottom of offer
- **Rationale:** Clear separation of pricing vs. payment terms

### 3. Large File Refactoring
- **Decision:** Deferred - not blocking functionality
- **Rationale:** High risk, limited immediate benefit

---

## Open Technical Decisions

### DECISION-T001: Room Reservation Timing
**Impact:** Calendar blocking, conflict handling

**Question:** When should a room be blocked on the calendar?
- **Option A:** When client selects room (Step 3) - *current*
- **Option B:** When offer is sent
- **Option C:** When client accepts offer
- **Option D:** When deposit is paid

**Sub-question:** Should "Lead" status (interested but not committed) show on calendar?
- Current: Leads invisible
- Alternative: Show "3 leads interested in Feb 7" indicator

**Dependencies:** Calendar system, conflict resolution logic

---

### DECISION-T002: Room Conflict Resolution
**Impact:** Multi-client scenarios, fairness

**Question:** How to handle when two clients want the same room?

**Current implementation:**
- **Soft conflict:** Both can hold Option simultaneously → manager notified
- **Hard conflict:** One at Option, one tries Confirmed → system blocks second

**Options for soft conflicts:**
- A: Notify manager only (current)
- B: AI suggests alternatives to second client
- C: Block second client entirely (first-come-first-served)

---

### DECISION-T003: Multiple Rooms Per Event
**Impact:** Complex booking support

**Question:** Can a client hold multiple rooms for the same date?
- **Option A:** One room per event only (current)
- **Option B:** Allow multiple rooms per event (schema change needed)
- **Option C:** Require manager approval for multi-room

---

### DECISION-T004: Deposit Payment Verification (Production)
**Impact:** Security, compliance, accounting

**Question:** How to verify deposit payments in production?
- **Option A:** Trust client confirmation (testing only)
- **Option B:** Payment gateway webhook (Stripe/PayPal)
- **Option C:** Manual verification by manager
- **Option D:** Invoice-based bank transfer matching

**Recommendation:** Option B or D for production

---

### DECISION-T005: Deposit Changes After Payment
**Impact:** Refund policy, legal compliance

**Question:** What happens if event changes after deposit paid?

**Scenarios:**
1. **Deposit increases:** Request additional? Honor original?
2. **Deposit decreases:** Refund difference? Apply as credit?
3. **Event cancelled:** Full refund? Partial? Apply to future?

**Dependencies:** Legal/finance team input, refund infrastructure

---

### DECISION-T006: Database Cleanup Strategy
**Impact:** Performance, GDPR compliance, storage costs

**Question:** How to handle old/stale data?

| Data Type | Current | Proposed |
|-----------|---------|----------|
| Events | Keep forever | Archive after 2 years? |
| Clients | Keep forever | **KEEP** (personalization) |
| HIL Tasks | Keep forever | Archive resolved after 90 days? |
| Debug traces | Keep forever | Delete in production |
| Conversations | Until restart | Expire after 24h inactivity? |

**Recommendation:** TTL-based cleanup + event-driven archival

---

### DECISION-T007: Client Memory & Personalization
**Impact:** Personalization quality, cost, privacy

**Question:** What should the system remember about returning clients?

**Extraction candidates:**
- Preferred language (already captured)
- Room preferences (from past bookings)
- Catering preferences (from past bookings)
- Budget sensitivity (LLM inference)
- Communication style (LLM inference)

**Options:**
- A: Minimal - messages only
- B: Rule-based extraction (obvious signals)
- C: LLM extraction (rich profiles, costly)
- D: Hybrid (rules + batch LLM)

**Recommendation:** Option D (Hybrid)

---

### DECISION-T008: Client Cancellation Flow
**Impact:** Critical UX feature gap

**Question:** How should client cancellations be handled?

**Current:** Not implemented - no way for client to cancel via email

**Proposed flow:**
1. Detect cancellation intent ("cancel", "abort", etc.)
2. Confirm with client (show event details)
3. Handle site visit (keep if before event, cancel if after)
4. Update event status, notify manager

**Dependencies:** Intent detection, site visit linkage

---

### DECISION-T009: Site Visit Timing
**Impact:** Workflow sequence, UX

**Question:** When should site visits be offered?

**Options:**
- A: Before offer (client sees venue before committing) - *recommended*
- B: After acceptance (current - feels like afterthought)
- C: Any time (flexible but complex)

**Challenge:** "Site visit date" vs "Event date" could be confused

---

### DECISION-T010: Missing Product Handling
**Impact:** HIL workflow, offer accuracy

**Problem:** System incorrectly claims items are included when they're not

**Expected behavior:**
1. Detect missing items from client request
2. Inform client clearly what's missing
3. Offer to source if client interested
4. Manager finds product → adds to offer
5. Resend updated offer if needed

**Dependencies:** Room data cleanup (features vs. equipment), HIL task extension

---

### DECISION-T011: Rate Limiting Values
**Impact:** Security, cost protection

**Question:** What rate limits for production?

**Suggested starting point:**
- 10 requests per second per IP
- 25 burst allowance

**Per-route limits (future):**
- LLM endpoints: Lower (expensive)
- Static data: Higher (cheap)

---

### DECISION-T012: Local LLMs for Detection
**Impact:** Cost optimization

**Question:** Use free local LLMs (Ollama) for detection tasks?

**Use cases:**
- Confirmation detection
- Sentiment fallback
- Language detection
- Intent disambiguation

**Trade-offs:**
- Cost: Free (after setup)
- Speed: 2-5s (acceptable with response timers)
- Quality: Slightly lower than cloud LLMs

---

## Integration Blockers

These need resolution before production integration:

### 1. HIL Communication Flow
**Question:** How does frontend notify backend when manager approves?
- A: Frontend calls backend API
- B: Poll database for task status
- C: Database webhook to backend

### 2. Email Trigger Mechanism
**Question:** How does new email trigger workflow?
- A: Frontend calls API
- B: Email webhook
- C: Poll emails table

### 3. Real-time Updates
**Question:** How does frontend know when AI creates task?
- A: Database real-time subscriptions
- B: Frontend polling
- C: WebSocket from backend

---

## Environment Configuration

These settings control behavior and should be documented:

| Setting | Purpose | MVP Default |
|---------|---------|-------------|
| `OE_HIL_ALL_LLM_REPLIES` | Require approval for all AI messages | `true` |
| `RATE_LIMIT_ENABLED` | Enable rate limiting | `0` (disabled for dev) |
| `DEBUG_TRACE` | Enable debug traces | `1` (dev) / `0` (prod) |
| `AGENT_MODE` | LLM behavior | `openai` (live) or `stub` (test) |

---

*This document tracks technical decisions. Update when decisions are made.*
