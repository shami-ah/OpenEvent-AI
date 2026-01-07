"""Smoke test for OpenAI client connectivity via centralized singleton."""

import pytest

pytestmark = pytest.mark.v4

from llm.client import get_openai_client, is_llm_available


def test_agent_smoke():
    """Verify OpenAI client can connect and list models."""
    if not is_llm_available():
        pytest.skip("LLM not available (no API key or stub mode)")

    client = get_openai_client()
    first = next(iter(client.models.list().data), None)
    assert first is not None, "Should be able to list at least one model"
