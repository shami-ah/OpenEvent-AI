# LLM Hallucination Prevention for Crucial Facts

**Last Updated:** 2025-12-22

## Overview

This document describes the two-layer defense system that prevents LLM hallucination of crucial facts (dates, prices, room names, participant counts, product names, features).

## Architecture: Defense in Depth

```
Client message
     │
     ▼
┌─────────────────────────────────────────┐
│  LAYER 1: LLM Prompt Instructions       │
│  "Extract exactly, don't translate"     │
└─────────────────────────────────────────┘
     │
     ▼
┌─────────────────────────────────────────┐
│  Deterministic Date Parsing             │
│  parse_first_date() → to_ddmmyyyy()     │
└─────────────────────────────────────────┘
     │
     ▼
┌─────────────────────────────────────────┐
│  LAYER 2: Safety Sandwich               │
│  verify_output() → correct_output()     │
└─────────────────────────────────────────┘
     │
     ▼
Client response (verified & corrected)
```

## Layer 1: LLM Prompt Instructions

### Purpose
Instruct the LLM to preserve facts correctly at the source, reducing the likelihood of hallucination before verification.

### Extraction Prompts

**Location:** `backend/workflows/qna/extraction.py`, `backend/adapters/agent_adapter.py`

**Rules:**
1. **DATES**: Normalize to YYYY-MM-DD format
   - "8th August 2026" → "2026-08-08"
   - "14 February" → "2026-02-14"

2. **TIMES**: Normalize to HH:MM format
   - "6pm" → "18:00"

3. **NUMBERS**: Extract exactly as stated
   - "30 people" → 30

4. **NON-NUMERIC TERMS**: Extract EXACTLY as written, NEVER translate
   - Room names: "Punkt.Null" stays "Punkt.Null" (not "Point Zero")
   - Features: "projector" stays "projector" (not "Beamer")
   - Products: "Apéro Package" stays "Apéro Package" (not "appetizer package")

### Verbalizer Prompts

**Location:** `backend/llm/verbalizer_agent.py`, `backend/ux/universal_verbalizer.py`, `backend/workflows/qna/verbalizer.py`

**Rules:**
1. MUST include ALL dates exactly as provided (DD.MM.YYYY format)
2. MUST include ALL room names exactly as provided
3. MUST include ALL prices exactly as provided (CHF format)
4. MUST include participant count if provided
5. MUST NOT invent new dates, prices, room names, or numeric values
6. MUST NOT translate or reformulate database terms
7. Gatekeeping variables (date, room, participants, prices) must match exactly

## Layer 2: Safety Sandwich (Deterministic Verification)

### Purpose
Catch and correct any hallucinations that slip through Layer 1.

### Components

**Location:** `backend/ux/verbalizer_safety.py`

#### 1. Hard Facts Extraction

```python
@dataclass
class HardFacts:
    dates: Set[str]           # DD.MM.YYYY format (normalized)
    room_names: Set[str]      # Exact room names
    currency_amounts: Set[str] # CHF amounts
    numeric_counts: Set[str]  # Participant counts, capacities
    time_strings: Set[str]    # Time ranges like "18:00–22:00"
```

#### 2. Verification (`verify_output`)

Checks:
- All canonical facts appear in LLM output (missing_facts)
- No invented facts appear in LLM output (invented_facts)

```python
result = verify_output(facts, llm_text)
if not result.ok:
    # Missing facts: dates, room_names, amounts not in output
    # Invented facts: dates, amounts in output not in canonical
```

#### 3. Correction (`correct_output`)

Instead of rejecting, the system FIXES the output:
- **Missing facts** → INSERT at appropriate location
- **Wrong facts** → REPLACE with correct value
- **Hallucinated facts** → REMOVE from text

```python
corrected_text, was_corrected = correct_output(facts, llm_text)
```

#### 4. Term Protection (Marker System)

For non-numeric terms that LLMs might translate:

```python
# Before LLM call
protected_text, markers = protect_terms(text, facts)
# "Room A with projector" → "Room A with {{FEATURE_0}}"

# After LLM call
restored_text = restore_terms(llm_output, markers)
# "Room A with {{FEATURE_0}}" → "Room A with projector"
```

## Date Normalization Flow

```
1. Client writes: "8 August 2026" (text)
2. LLM extracts: "2026-08-08" (ISO for DB)
3. Facts builder: "08.08.2026" (DD.MM.YYYY for verification)
4. Verification: checks LLM output contains "08.08.2026"
```

**Key:** Verification checks against the NORMALIZED format, not the original client text.

## Files Reference

| File | Purpose |
|------|---------|
| `backend/ux/verbalizer_safety.py` | Core sandwich: verify, correct, protect terms |
| `backend/workflows/qna/extraction.py` | QnA extraction prompt with rules |
| `backend/adapters/agent_adapter.py` | Entity extraction prompt with rules |
| `backend/llm/verbalizer_agent.py` | Room/offer verbalizer prompt |
| `backend/ux/universal_verbalizer.py` | Universal verbalizer prompt |
| `backend/workflows/qna/verbalizer.py` | QnA verbalizer with sandwich wiring |
| `backend/workflows/common/datetime_parse.py` | Deterministic date parsing |

## Error Messages

When Layer 2 cannot fix an issue, clear error messages are shown:

| Error | Meaning |
|-------|---------|
| `[EXTRACTION ERROR]` | LLM extraction failed/disabled, cannot proceed |
| `[DATA ERROR]` | No database results for the query |
| `[SYSTEM FALLBACK]` | Verbalizer could not generate response |

## Testing

Regression tests in `backend/tests/regression/test_sandwich_validation.py`:
- `test_verify_output_*` - Verification logic
- `test_correct_output_*` - Correction logic
- `test_protect_terms_*` - Term protection
- `test_build_facts_*` - Facts extraction

## When to Update

Add new prompt rules when:
1. A new type of database term is added that LLMs might translate
2. A new gatekeeping variable is introduced
3. A new hallucination pattern is observed

Update sandwich verification when:
1. A new fact type needs to be verified
2. New extraction/correction patterns are needed
