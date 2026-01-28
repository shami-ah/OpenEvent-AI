# MVP Feature Requirements for Design/Web Team

**Date:** January 12, 2026
**Purpose:** Feature list for OpenEvent AI Assistant frontend
**Audience:** Design and Web Team

---

## What This Application Does

The AI Assistant helps event managers handle client bookings via email. When a client sends an email:
1. The AI reads the email and drafts a response
2. The manager reviews and approves (or edits) before sending
3. The conversation continues until the offer is confirmed

The manager sees this integrated into their email inbox - not as a separate chat app.

---

# Section 1: Core Features (Must Have)

## 1.1 Email Conversation View

Display the email conversation between the manager's venue and the client.

- Show messages in order (oldest to newest)
- Each message shows: who sent it, when, and the content
- Clear visual difference between:
  - **Client messages** (received emails)
  - **AI drafts** (waiting for manager approval - NOT sent yet)
  - **Sent messages** (approved and delivered to client)

---

## 1.2 AI Agent Section (Manager Approves AI Replies)

When the AI creates a response to a client email, the manager must review it before sending.

**Features needed:**
- Show the AI's draft message clearly marked as "Draft - Awaiting Approval"
- **Edit field**: Manager can modify the text before sending
- **Approve & Send button**: Send the message to the client
- **Reject button**: Discard the draft (AI will try again or manager writes own response)
- **Notes field** (optional): Internal notes, not visible to client

**Important:** Every AI-generated message goes through this approval before the client sees it.

---

## 1.3 Client Review Section (Manager Handles Special Cases)

Some client messages need manager attention beyond just approving AI replies.

**1.3.1 Special Product Requests**

When a client asks for something not in the standard catalog (e.g., "We need a red carpet"):
- Show what the client requested
- **Product name field**: Manager enters the product they found
- **Price field (CHF)**: Manager enters the price
- **"Add to Offer" button**: Includes the product in the offer
- **"Not Available" button**: AI informs client it's unavailable

**1.3.2 Room Conflict Resolution**

When two clients both select the same room on the same date (both have "Option" status), the manager must decide who gets it.

**What the manager sees:**
- Conflict notification: "Client A and Client B both want Room X on Feb 7"
- **Client 1 info**: Name, email (first to reserve - preferred by default)
- **Client 2 info**: Name, email, reason for wanting this room (if provided)
- Room and date in conflict

**GUI components needed:**
- **"Assign to Client 1" button**: First holder gets the room (default preference)
- **"Assign to Client 2" button**: Client 2 gets the room if they have a better reason
- The other client is automatically notified and offered alternatives (different room or date)

---

**1.3.3 Message Review (Edge Cases)**

When the AI isn't sure about a message (unusual request, unclear intent, potential spam):
- Show the client's message
- Manager decides how to respond (or marks as spam)

---

# Section 2: Offer & Deposit Features

## 2.1 Deposit Management (Manager Side)

The deposit is paid outside the system (bank transfer, etc.). The manager needs to track it.

**Features needed:**
- **Deposit status display**: Show if deposit is "Pending" or "Paid" for each client
- **"Mark Deposit Paid" button**: Manager clicks this when they've received the deposit

**Note:** The client does not interact with deposit features in the GUI - they receive deposit information in the offer email and pay externally.

---

## 2.2 Offer Confirmation

When all requirements are met and deposit is paid:
- **Confirm Offer button**: Finalize the event
- **Reject button**: Decline with optional reason

---

# Section 3: Configuration / Admin

## 3.1 Global Deposit Settings (MVP)

One global setting that applies to all offers:
- **Toggle**: Deposits on/off
- **Type selector**:
  - Fixed amount (e.g., CHF 500) - can be mentioned early in conversation
  - Percentage (e.g., 30% of total) - calculated when offer is created
- **Deadline**: Days until payment due (7, 10, 14, or 30 days)

---

## 3.2 AI Settings (Post-MVP / Optional)

*Not priority for MVP - implement if time allows*

- Choose AI quality level (affects cost and response quality)
- View estimated cost per message

---

## 3.3 Prompt Editor (Post-MVP / Optional)

*Not priority for MVP - implement if time allows*

- Edit the AI's instructions
- View and revert to previous versions

---

# Section 4: Open Decisions

These need team input before final design.

---

## Open Decision 1: Email View Style

**Question:** How should conversations be displayed?

**Current default:** Traditional email thread (Option B)

| Option | Description | Advantages | Disadvantages |
|--------|-------------|------------|---------------|
| **A** | Chat-style (like WhatsApp) | Clearer organization, easier to follow conversation flow, modern feel | Less familiar to email-heavy users |
| **B** | Traditional email thread | Familiar to managers, all clients in one inbox | Can be harder to track individual conversations |
| **C** | Hybrid - toggle between views | Best of both worlds | More complex to build |

---

## Open Decision 2: Client Information Overview

**Question:** Should the manager see an overview panel for each client conversation?

If yes, what should it show?
- Client name and email
- Which step of the process (e.g., "Discussing rooms")
- What's confirmed: date, room, number of guests
- What's still needed: date not confirmed, room not selected, etc.
- Event type, special requirements

**Options:**
| Option | Description |
|--------|-------------|
| **A** | Yes - always visible sidebar |
| **B** | Yes - collapsible panel |
| **C** | No - just show conversation |

---

## Open Decision 3: When to Show Deposit Information

**Question:** When should the client first see deposit requirements?

| Option | Description |
|--------|-------------|
| **A** | In the first AI reply (for fixed deposits that can be paid immediately) |
| **B** | Only in the formal offer (current behavior) |
| **C** | Early mention, then detailed in offer |

**Context:**
- Fixed deposits (e.g., CHF 500) could theoretically be paid from the start
- Percentage deposits (e.g., 30% of total) can only be calculated once the offer is ready
- Currently, the AI only mentions deposit in the offer confirmation step

---

## Open Decision 4: Progress Visualization

**Question:** How to show where each client is in the process?

| Option | Description |
|--------|-------------|
| **A** | Simple text: "Step 3: Room Selection" |
| **B** | Visual progress bar |
| **C** | Checklist: ✓ Date confirmed, ✓ Room selected, ○ Offer pending |
| **D** | No progress indicator |

---

## Open Decision 5: Thread Closure

**Question:** When is a conversation considered "closed"?

| Option | Description |
|--------|-------------|
| **A** | When offer is confirmed or cancelled |
| **B** | After X days of no activity |
| **C** | Manager manually closes it |
| **D** | Combination |

---

## Open Decision 6: Deposit Payment Verification

**Question:** How does the manager mark that the deposit was paid?

| Option | Description |
|--------|-------------|
| **A** | Simple button "Mark as Paid" (recommended for MVP) |
| **B** | Button with confirmation dialog |
| **C** | Form with payment date and reference number |

**Recommendation:** Option A for MVP, can add more details later if needed.

---

## Open Decision 7: Quick Action Buttons

**Question:** Should there be quick action buttons directly in the email view?

Suggested buttons:
- Approve & Send
- Edit & Send
- Reject
- Hold (keep for later)

**Decision:** Which buttons are needed? All, some, or none?

---

# Backend Note: Email Thread Assignment

**Important context for frontend development:**

The backend currently assumes clients reply to existing emails (using email threading). The following is **not yet implemented** on the backend:

- **Recognizing incoming emails**: Matching a new email to the correct client/conversation thread
- **Handling fresh emails**: What if a client sends a new email instead of replying to an existing one? Can we still correctly assign it to their thread?
- **100% accurate thread matching**: Currently not guaranteed

**What this means for frontend:**
- For MVP, we may need to assume emails come in as replies (with proper email threading headers)
- Manual thread assignment by manager may be needed as a fallback
- This is a backend task to be completed before full email integration works

**Current workaround:** The development/testing version uses a chat interface where thread assignment is automatic (each session = one thread).

---

# Features NOT in MVP

These are planned for later, not the initial release:

- **Info Pages**: Detailed room/catering browsing (managers know their rooms)
- **Calendar View**: Visual room availability calendar
- **Per-Room Deposits**: Individual room deposit settings
- **Multiple Venues**: Support for more than one venue
- **Advanced Analytics**: Statistics and reports
- **Client-facing deposit payment**: Clients pay outside the system for now
- **Site visit scheduling UI**: Backend feature, not GUI

---

# Visual Design Suggestions

These are suggestions from development - adapt as needed:

**Color Coding:**
- Green: Confirmed / Success / Sent
- Yellow/Orange: Pending / Waiting for action
- Red: Error / Rejected / Unavailable
- Blue: Informational

**Message States:**
- Client message: One style
- AI draft (pending): Different style, clearly marked as "not sent yet"
- Sent message: Another style showing it was delivered

**Cards/Panels:**
- Group related information in clear, separated sections
- Use consistent spacing and hierarchy

---

# Implementation Priority

**Phase 1 - Core:**
1. Email conversation view
2. AI draft approval (edit, approve, reject)
3. Special product request handling
4. Room conflict resolution
5. Message review for edge cases

**Phase 2 - Offers:**
1. Deposit status display and "Mark as Paid" button
2. Global deposit settings (fixed/percentage, deadline)
3. Offer confirmation (confirm/reject)

**Phase 3 - Optional (if time allows):**
1. Client info overview (if decided yes)
2. Progress indicators (if decided yes)
3. AI settings
4. Prompt editor

---

*This document will be updated as decisions are made.*
