#!/bin/sh
# Source this script to load the OpenEvent-AI dev environment.
# Usage: . scripts/dev/oe_env.sh
#
# Loads:
#   - PYTHONPATH for imports
#   - OPENAI_API_KEY from Keychain (for verification LLM)
#   - GOOGLE_API_KEY from Keychain (for Gemini intent/extraction)
#   - VERBALIZER_TONE default

export PYTHONPATH="$(pwd -P)"
export OPENAI_API_KEY="$(security find-generic-password -a "$USER" -s 'openevent-api-test-key' -w 2>/dev/null || true)"
export GOOGLE_API_KEY="$(security find-generic-password -s 'openevent-gemini-key' -w 2>/dev/null || true)"

# Default to empathetic verbalizer (human-like UX) for development
# Set VERBALIZER_TONE=plain to disable LLM verbalization for testing
export VERBALIZER_TONE="${VERBALIZER_TONE:-empathetic}"

# Status output
_oe_status=""
[ -n "$OPENAI_API_KEY" ] && _oe_status="${_oe_status}OpenAI:✓ " || _oe_status="${_oe_status}OpenAI:✗ "
[ -n "$GOOGLE_API_KEY" ] && _oe_status="${_oe_status}Gemini:✓" || _oe_status="${_oe_status}Gemini:✗"

if [ -n "$OPENAI_API_KEY" ] && [ -n "$GOOGLE_API_KEY" ]; then
  echo "OpenEvent-AI env activated [${_oe_status}] - Hybrid mode ready" >&2
else
  echo "OpenEvent-AI env activated [${_oe_status}] - Missing keys for hybrid mode" >&2
fi
unset _oe_status

