# OpenEvent AI Test Report - December 30, 2025

## Executive Summary

Comprehensive testing of the OpenEvent AI workflow system revealed a **mixed picture**: core booking flows work well, but several edge cases and detection scenarios need attention.

**Overall Score: 6.5/10**

| Category | Status | Score |
|----------|--------|-------|
| Core Booking Flow | Working | 8/10 |
| Intent Detection | Partial | 6/10 |
| Hybrid Mode (Gemini/OpenAI) | Working | 9/10 |
| Provider Fallback | Working | 9/10 |
| Out-of-Context Handling | Working | 8/10 |
| Q&A Integration | Partial | 5/10 |
| Date Change Detours | Working | 8/10 |
| UX/UI Quality | Good | 7/10 |

---

## Test Environment

- **Backend**: FastAPI on localhost:8000
- **Frontend**: Next.js on localhost:3000
- **LLM Mode**: HYBRID (E:gemini, V:openai)
- **Detection Mode**: Unified
- **Test Method**: API calls + Playwright E2E

---

## Detailed Findings

### 1. Core Booking Flow (PASS)

**Test**: Complete booking from initial request to room offer.

```
Client: "Room for 20 people on 15.03.2026. Projector required."
AI: Room recommendation with availability overview
```

**Result**: Working correctly. The system:
- Extracts date, capacity, and requirements
- Recommends appropriate room
- Provides availability link
- Includes catering suggestions

**UX Note**: Response is well-formatted with markdown, clear pricing.

---

### 2. Intent Detection Issues (PARTIAL)

#### 2.1 Capacity Parsing Bug (BUG)

**Issue**: Year from date sometimes parsed as capacity.

```
Input: "Date: 13.02.2026, Participants: 25 people"
Result: Capacity detected as 2026 (from date)
Action: capacity_exceeded
```

**Impact**: Medium - causes incorrect workflow routing.

#### 2.2 JSON Parse Errors (HANDLED)

**Observed**: OpenAI detection returning malformed JSON:
```
[OpenAIAgentAdapter] complete error: Error code: 400 - 'messages' must contain the word 'json'
[UNIFIED_DETECTION] JSON parse error: Unterminated string starting at: line 25
```

**Result**: Fallback to Gemini works correctly!
```
[UNIFIED_DETECTION] Trying fallback provider: gemini
[UNIFIED_DETECTION] intent=event_request, manager=False
```

#### 2.3 max_tokens Issue (BUG)

**Observed**:
```
Error code: 400 - 'max_tokens or model output limit was reached'
```

**Impact**: Detection fails, falls back to general_qna, routes to manual_review.

---

### 3. Hybrid Mode (PASS)

**Test**: Verify Gemini for extraction, OpenAI for verbalization.

**Result**: Working correctly!
- Status bar shows: `HYBRID | E:gem | V:ope | Safe`
- Detection uses Gemini (cheaper)
- Verbalization uses OpenAI (better prose quality)
- Provider fallback chain working: gemini -> openai, openai -> gemini

---

### 4. Out-of-Context Handling (PASS)

**Test**: Send step-specific intent at wrong workflow step.

```
Current Step: 3 (Room Availability)
Client: "Yes, I confirm the date 28.02.2026"
```

**Result**:
```
[UNIFIED_DETECTION] intent=confirm_date, manager=False, conf=True
[OUT_OF_CONTEXT] Intent 'confirm_date' is only valid at steps {2}, but current step is 3
[PRE_ROUTE] Out-of-context message detected - no response
```

**Behavior**: Returns empty response (correct - ignores out-of-context).

---

### 5. Q&A Mid-Flow (PARTIAL)

**Test**: Ask general question during booking flow.

```
Scenario: Room booked, then ask "Do you have parking?"
```

**Issues Observed**:
1. Some Q&A requests route to manual_review when no event exists
2. Q&A detection sometimes misclassified as event_request
3. When event exists, Q&A works but may get stuck asking for billing address

**Recommendation**: Q&A should work independently of workflow state.

---

### 6. Date Change Detour (PASS)

**Test**: Change date mid-flow.

```
Client: "Actually, change the date to 10.04.2026"
```

**Result**:
```
[UNIFIED_DETECTION] intent=edit_date, manager=False
AI: "Great, I've noted 10.04.2026. What time works best?"
```

**Behavior**: Correctly detects date change, re-enters workflow.

---

### 7. Manager Request (PASS)

**Test**: Request to speak with manager.

```
Client: "I'd like to speak with a manager about special arrangements"
```

**Result**:
```
[UNIFIED_DETECTION] intent=message_manager, manager=True
[PRE_ROUTE] Manager escalation detected - creating HIL task
AI: "I understand you'd like to speak with a manager. I've forwarded your request..."
```

**Behavior**: Correctly escalates to Human-in-Loop.

---

### 8. Mixed Intents (PARTIAL)

**Test**: Message with multiple intents.

```
Client: "What are your opening hours? Also, change to 10.03.2026"
```

**Result**: Only date change handled, Q&A ignored.

**Recommendation**: Either handle primary intent and queue secondary, or respond to both.

---

## UX Observations

### Positive

1. **Clean chat interface** with clear sender identification
2. **Status bar** shows configuration (HYBRID, deposit %, etc.)
3. **Typing indicator** ("Shami is typing...") provides feedback
4. **Formatted responses** with markdown, bold dates/counts
5. **Quick reset** buttons (Clear Tasks, Reset Client)

### Issues

1. **Stuck loops**: Workflow sometimes repeats same question
   - "What time works best for you?" asked repeatedly

2. **Billing address request** appears early in some flows before room confirmation

3. **No visible step indicator** in chat - only in status bar footer

4. **Response latency**: ~3-5 seconds visible in typing indicator

---

## Logic Flow Issues

### Issue 1: Premature Billing Request

```
Flow observed:
1. Client: "Meeting room for 25 guests on 20.03.2026"
2. AI: "Thanks for confirming. I need the billing address..."
```

**Problem**: Jumps to billing before room selection/confirmation.

### Issue 2: Workflow Stuck State

After certain interactions, workflow gets stuck asking:
```
"Great, I've noted [date]. What time works best for you?"
```

This repeats regardless of client input.

### Issue 3: Manual Review Over-routing

Many simple requests go to manual_review when:
- No existing event entry found
- Detection returns low confidence
- JSON parsing fails

**Recommendation**: Implement graceful degradation instead of manual_review.

---

## Provider Fallback Verification

**Test**: Simulated Gemini failure.

```python
# Mock Gemini returning invalid JSON
result = run_detection("I confirm the date")
```

**Result**:
```
[UNIFIED_DETECTION] JSON parse error with gemini
[UNIFIED_DETECTION] Trying fallback provider: openai
Intent: confirm_date, Confidence: 1.0
```

**Status**: WORKING - Fallback chain executes correctly.

---

## Recommendations

### High Priority

1. **Fix capacity parsing** - Don't extract year from date as capacity
2. **Increase max_tokens** for detection to prevent truncation errors
3. **Fix workflow stuck state** - Prevent repetitive time questions

### Medium Priority

4. **Improve Q&A handling** - Should work without existing event
5. **Mixed intent support** - Handle multiple intents in single message
6. **Step visibility** - Show current workflow step in chat

### Low Priority

7. **Latency optimization** - Cache common Q&A responses
8. **Manual review reduction** - Graceful fallback instead of escalation

---

## Test Files Generated

| File | Description |
|------|-------------|
| `/tmp/test_results.json` | API test results |
| `/tmp/pw_*.png` | Playwright screenshots |
| `/tmp/server.log` | Backend logs |

---

## Conclusion

The OpenEvent AI system demonstrates solid core functionality with working hybrid mode, provider fallback, and out-of-context handling. The main areas needing attention are:

1. Detection edge cases (capacity parsing, max_tokens)
2. Workflow stuck states
3. Q&A integration with event flow

The UX is professional and responsive, with room for improvement in step visibility and error handling.

---

*Report generated: 2025-12-30 17:52 CET*
*Test framework: Python requests + Playwright E2E*
