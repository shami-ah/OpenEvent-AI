# Strategy: Dual-Engine Architecture (OpenAI + Gemini)

**Status:** Proposed
**Date:** December 22, 2025
**Goal:** Integrate Google Gemini Flash alongside OpenAI to reduce costs by ~80% and enable "No-Regex" robustness, while maintaining 100% backward compatibility and instant fallback to GPT-4o-mini.

## 1. The Core Concept (Hybrid & Toggle)
Instead of a "rip and replace," we will **extend** the current `LLMProvider` system. The application will be able to run in three modes via a simple config change:
1.  **OpenAI Mode (Current):** Uses GPT-4o/mini. Safe, proven fallback.
2.  **Gemini Mode (Target):** Uses Gemini 2.0 Flash / 1.5 Flash. Low cost, high context.
3.  **Hybrid Mode:** Uses OpenAI for complex reasoning (Step 5 Negotiation) and Gemini Flash for high-volume tasks (Extraction, Summarization, "Regex Replacement").

## 2. Cost Analysis (The "Why")

| Task Type | Current Model | Cost (Input/Output per 1M) | Proposed Model | Cost (Input/Output per 1M) | Savings Factor |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Complex Logic** | GPT-4o | $2.50 / $10.00 | **Gemini 2.0 Flash** | **~$0.10 / $0.40** (or Free) | **~25x cheaper** |
| **Simple Logic** | GPT-4o-mini | $0.15 / $0.60 | **Gemini 1.5 Flash** | **$0.075 / $0.30** | **~2x cheaper** |
| **Extraction** | Regex | $0.00 (High Dev Cost) | **Gemini 1.5 Flash-8B** | **$0.0375 / $0.15** | **Negligible Cost** |

**The "Regex" Economics:**
- **Regex:** Free to run, expensive to write/debug. Fails on typos.
- **Flash-8B:** Costs ~$0.00002 per call. You can run **50,000 extractions for $1.00**.
- **Conclusion:** It is cheaper to pay $1 for 50k robust extractions than to spend 1 hour of developer time fixing a broken Regex.

## 3. Implementation Plan (Minimally Invasive)

### Phase 1: Add Gemini Capability (No Breaking Changes)
- [ ] **Extend Registry:** Add `GeminiProvider` class implementing the existing `BaseLLMProvider` interface.
- [ ] **Config Update:** Update `configs/llm_profiles.json` to define new profiles (e.g., `gemini-v1`, `hybrid-v1`) without touching the existing `v1-current`.
- [ ] **Environment:** Add `GEMINI_API_KEY` support to `backend/config.py`.

### Phase 2: The Toggle Switch
- [ ] The system already selects the active profile via `OE_LLM_PROFILE` env var.
- [ ] **Action:** To switch to Gemini, we simply set `OE_LLM_PROFILE=gemini-v1`.
- [ ] **Fallback:** If issues arise, we revert `OE_LLM_PROFILE` to `v1-current` (OpenAI). Zero code changes required for rollback.

### Phase 3: "Regex Killer" as a Hybrid Service
- [ ] Instead of deleting Regex code, wrap it in a feature flag or a new helper: `extract_date(text, use_llm=True)`.
- [ ] This helper checks the config. If `use_llm` is enabled, it calls Gemini Flash-8B. If disabled (or if Gemini fails), it falls back to the legacy Regex logic.
- [ ] This provides a safety net: "Try Smart Extraction -> Fallback to Regex".

## 4. Technical Details

**`configs/llm_profiles.json` Structure:**
```json
{
  "openai-standard": {
    "provider": "openai",
    "main_model": "gpt-4o-mini",
    "fast_model": "gpt-4o-mini"
  },
  "gemini-flash": {
    "provider": "gemini",
    "main_model": "gemini-2.0-flash-exp",
    "fast_model": "gemini-1.5-flash-8b"
  },
  "hybrid": {
    "provider": "hybrid",
    "main_model": "gpt-4o",  // Use OpenAI for hard stuff
    "fast_model": "gemini-1.5-flash-8b" // Use Gemini for easy stuff
  }
}
```

## 5. Decision
**Proceed with Phase 1 & 2.** This allows us to test Gemini in production with zero risk, as the "off switch" is immediate and reliable.