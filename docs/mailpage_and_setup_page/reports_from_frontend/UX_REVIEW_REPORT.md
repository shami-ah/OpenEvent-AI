# UX Review Report: Event Request Feature

**Date:** 2026-01-26
**Reviewer:** Gemini (Consolidated Review - 2nd & 3rd Specialist)
**Status:** Approved with Required Improvements

---

## Executive Summary

The proposed design for the "Event Request Inbox" and "Event Request Setup" is **highly aligned with current state-of-the-art (SOTA) patterns** for 2025/2026 event management software. It effectively addresses the "Human-in-the-Loop" (HITL) requirement, balancing automation with the control event managers crave.

The design correctly identifies the primary pain points (double-booking fear, email overload) and uses established patterns (Activity Feeds, Progressive Disclosure) to solve them.

However, based on deep research into AI Agent UIs (e.g., Microsoft Copilot for Sales, Tripleseat's latest automation features), several critical enhancements are required to ensure **Trust** and **Mobile Usability**. Specifically, the "Black Box" nature of AI decisions must be mitigated with **Source Grounding** and **Confidence Indicators**.

---

## Detailed Checklist Review

### 1. Information Architecture
**Status:** ✅ **Approved**
- **Inbox Placement:** Placing "Event Requests" as a tab in `/inbox` is excellent. It meets the user where they spend 50% of their time.
- **3-Panel Layout:** Standard and effective for high-volume processing. Matches patterns in Outlook, Superhuman, and Front.
- **Prioritization:** The "Alerts" panel taking precedence over "Event Details" is a crucial "management by exception" design choice.

### 2. Vocabulary & Terminology
**Status:** ✅ **Approved**
- **Consistency:** Terms like "Lead", "Option", "Confirmed" match the `FRONTEND_REFERENCE.md` and industry standards (Tripleseat, Planning Pod).
- **Naming:** "Event Requests" is clear. "AI Draft" and "Automation Mode" are intuitive.

### 3. Event Details Panel — Progressive Disclosure
**Status:** ✅ **Approved**
- **Logic:** The split between core fields and stage-dependent fields is sound. It prevents "empty state anxiety."
- **Completeness:** Covers all essential fields mapped in `FRONTEND_REFERENCE.md`.

### 4. Alerts Panel — Decision Making
**Status:** ⚠️ **Approved with Improvements**
- **Issue:** "Date Conflict" actions ("Accept New" / "Keep Existing") are too binary.
- **Refinement:** Real-world negotiations are often nuanced.
- **Requirement:** Add a **"Suggest Alternative Time"** action. This uses the AI to proactively find gaps, rather than just rejecting. This is a common feature in modern scheduling tools (e.g., Calendly, Motion).

### 5. AI Activity Panel — Transparency & Trust (CRITICAL)
**Status:** ⚠️ **Needs Improvement**
- **Issue:** The feed shows *what* happened, but not *why* or *where* the data came from. SOTA AI interfaces (Copilot) use **Source Grounding**.
- **Requirement:**
    1.  **Source Highlighting:** When the AI extracts "150 attendees", hovering over that number in the Details Panel should ideally highlight the text *"expecting around 150 people"* in the email thread (if technically feasible) or at least show a tooltip: "Extracted from email body".
    2.  **Confidence Indicators:** If the AI is <80% sure (e.g., date format was ambiguous "01/02/26"), it **must** show a "Low Confidence" warning or question mark icon.
    3.  **Grouping:** Ensure the Activity Feed groups related actions (e.g., "AI handled negotiation" instead of 5 separate log lines for draft, check, update, etc.) to prevent noise.

### 6. AI Draft Approval Flow
**Status:** ✅ **Approved**
- **Inline Editing:** This is superior to a separate task list.
- **Actions:** "Edit", "Send Now", "Discard" are the correct primitives.
- **Requirement:** Add a **Feedback Loop**. A simple Thumbs Up/Down 👍/👎 icon on drafts (before sending) is standard SOTA to help train the specific model for that venue.

### 7. Setup Page — Settings Design
**Status:** ⚠️ **Approved with MVP Adjustments**
- **Automation Modes:** The 3-level split ("Review All", "Semi-Auto", "Full Auto") is perfect.
- **Missing MVP Criticals:** "Response Style" is marked as "Coming Soon", but **Signature** and **Tone** are critical for initial trust. If the AI sounds robotic or signs as "AI Bot", managers won't use it.
- **Requirement:** Move **"Email Signature"** and a basic **"Tone"** toggle (Formal/Friendly) to the MVP scope.

### 8. Interaction Design
**Status:** ⚠️ **Approved with Mobile Spec**
- **Mobile Experience:** The spec mentions "desktop primary, mobile for quick checks" but leaves the mobile layout ambiguous.
- **Requirement:** Explicitly define that on mobile, the 3-panel layout becomes a **drill-down navigation**: List → Thread → Details (in a drawer/sheet).

### 9. API Completeness
**Status:** ✅ **Approved**
- The endpoints cover the specified frontend interactions.

### 10. Edge Cases
**Status:** ⚠️ **Approved with Tasks Clarification**
- **Task Integration:** Clarify relationship with `/tasks`.
- **Requirement:** "Items in the Event Request Inbox are specialized tasks. They do **not** appear in the general `/tasks` Kanban board to avoid duplication, unless explicitly 'Flagged for Follow-up', which creates a linked Task entity."

---

## Final Recommendations (Prioritized)

### Priority 1: Mobile Layout Definition
**Location:** Section 3.2 (Page Layout)
**Action:** Add a subsection "Mobile Adaptation".
**Spec:**
> On mobile devices (<768px):
> 1. **List View:** Shows only the Thread List.
> 2. **Thread View:** Tapping a thread opens it in full screen.
> 3. **Context View:** The Right Panel (Details/Alerts) moves to a **Slide-over Sheet** accessible via an "Info" icon in the top header.

### Priority 2: "Suggest Alternative" Action
**Location:** Section 3.5.1 (Alerts Panel) -> Date Conflict
**Action:** Add a third action button: `[Suggest Alternatives]`.
**Reasoning:** Maximizes venue utilization by pivoting conflicts into sales.

### Priority 3: Source Grounding & Confidence
**Location:** Section 3.5.2 (Event Details)
**Action:** Add visual indicators (e.g., dotted underline) for AI-extracted fields.
**Spec:** "Hovering over an extracted field (Date, Attendees) should show a tooltip indicating the source confidence if below 100%."

### Priority 4: Tone & Signature in MVP
**Location:** Section 4.7 (Response Style)
**Action:** Move "Email Signature" and "Tone" (Simple Toggle) to MVP.
**Reasoning:** Essential for "Day 1" usability. Managers cannot send emails that don't look like them.

### Priority 5: Task Integration
**Location:** Section 3.1 (Page Location)
**Action:** Explicitly decouple from general `/tasks` unless flagged.

---

## Conclusion

The design is **robust, user-centric, and implementation-ready**. It avoids "AI gimmickry" in favor of practical workflow improvements. With the addition of Mobile specs, Source Grounding, and basic Personality settings (Tone/Signature), it will exceed the UX of market leaders.

**Recommendation:** **Proceed to Implementation** with the above 5 priority changes.