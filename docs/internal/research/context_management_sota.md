
## Overview
This document outlines the State-of-the-Art (SOTA) strategy for managing LLM context within the OpenEvent-AI workflow. Based on industry research, the project will move away from raw conversation history in favor of a **"Context Packet"** architecture to improve accuracy, reduce hallucinations, and minimize token costs.

## Core Principle: The "Context Packet"
Instead of feeding the entire chat thread into every agent, we provide a curated, structured snapshot.

**Formula:** `Current Message` + `Target Schema/Goal` + `Structured State Snapshot`

---

## Agent-Specific Strategies

### 1. Intent & Entity Extraction
*   **Context Strategy:** Current Message + Existing Event JSON + Target Schema.
*   **Why:** Prevents "Context Poisoning." If a user changes their mind (e.g., "Actually, make it 60 guests instead of 50"), the agent focuses on the *delta* (change) rather than getting confused by the old value present in the history.
*   **SOTA Benefit:** Eliminates re-extraction of stale data.

### 2. Unified Detection (Routing)
*   **Context Strategy:** Current Message + Current Workflow Step + **Last Assistant Question**.
*   **The "Anchor" Concept:** For short replies like "Yes," "Ok," or "That works," the agent needs the "Anchor" (the last question asked by the bot) to understand the intent.
*   **Why:** Routing based on full history often leads to "Context Distraction," where the LLM triggers an old intent mentioned earlier in the conversation.

### 3. Verbalization
*   **Context Strategy:** Structured Facts (Event State) + Current Step Goals.
*   **Why:** The verbalizer should be a deterministic reflection of the *truth* (the database/state). Including raw history often leads the LLM to mirror user tone inappropriately or hallucinate conversational details that were never committed to the state.

---

## Technical Implementation Guidelines

1.  **Last Question Injection:** In the workflow layer, capture the last `verbalized_text` sent to the user and include it as a 1-sentence "short-term memory" in the detection prompt.
2.  **State Delta Logic:** When extracting, explicitly instruct the LLM: *"Use the current message to update the existing state. If a value is not mentioned, do not guess."*
3.  **Sanitization:** Before passing the `current_message`, strip quoted email history or previous "Re:" blocks to prevent the LLM from seeing its own previous messages as new user input.

## Benefits
*   **Accuracy:** Significant reduction in false-positive intent detection.
*   **Latency:** Smaller prompts lead to faster Time-To-First-Token (TTFT).
*   **Cost:** 40-70% reduction in token usage for long conversations.
*   **Safety:** Prevents "Prompt Injection" via old messages in the history chain.
