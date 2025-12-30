"""
LLM Provider Configuration Helper.

Provides a centralized way to get the current LLM provider settings.
This is used by detection (intent/entity) and verbalization to determine
which LLM backend to use.

Hybrid Mode (default):
- Intent/Entity extraction: Gemini (cheaper, good for structured extraction)
- Verbalization: OpenAI (better quality for client-facing text)

Priority order:
1. Database setting (runtime toggle via admin UI)
2. Environment variables (INTENT_PROVIDER, ENTITY_PROVIDER, VERBALIZER_PROVIDER)
3. AGENT_MODE environment variable (sets all to same provider)
4. Defaults: gemini for extraction, openai for verbalization
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Literal, Optional

Provider = Literal["openai", "gemini", "stub"]

# Fallback chain: if primary fails, try these in order
# NOTE: No stub fallback in production - we want real LLM responses
PROVIDER_FALLBACK_CHAIN = {
    "gemini": ["openai"],  # Gemini fails → try OpenAI
    "openai": ["gemini"],  # OpenAI fails → try Gemini
    "stub": [],            # Stub has no fallback (only used in testing)
}


@dataclass
class LLMProviderSettings:
    """Current LLM provider settings."""
    intent_provider: Provider
    entity_provider: Provider
    verbalization_provider: Provider
    source: str  # "database", "environment", or "default"


def get_fallback_providers(primary: Provider) -> list:
    """Get fallback providers if primary fails."""
    return PROVIDER_FALLBACK_CHAIN.get(primary, ["stub"])


# Cache to avoid repeated database reads
_cached_settings: Optional[LLMProviderSettings] = None


def get_llm_providers(*, force_reload: bool = False) -> LLMProviderSettings:
    """
    Get the current LLM provider configuration.

    Checks in order:
    1. Database config (allows runtime toggle)
    2. Environment variables
    3. Defaults (hybrid mode)

    Args:
        force_reload: If True, bypass cache and reload from database

    Returns:
        LLMProviderSettings with current provider for each operation type
    """
    global _cached_settings

    if _cached_settings is not None and not force_reload:
        return _cached_settings

    # Try database first
    try:
        from backend.workflows.io.database import load_db
        db = load_db()
        llm_config = db.get("config", {}).get("llm_provider", {})

        if llm_config.get("intent_provider") or llm_config.get("entity_provider"):
            _cached_settings = LLMProviderSettings(
                intent_provider=llm_config.get("intent_provider", "gemini"),
                entity_provider=llm_config.get("entity_provider", "gemini"),
                verbalization_provider=llm_config.get("verbalization_provider", "openai"),
                source="database",
            )
            return _cached_settings
    except Exception:
        pass  # Database not available, use env/defaults

    # Fall back to environment variables
    agent_mode = os.getenv("AGENT_MODE", "").lower()

    # If AGENT_MODE is set, use it as default for extraction
    if agent_mode in ("openai", "gemini", "stub"):
        default_extraction = agent_mode
    else:
        default_extraction = "gemini"  # Default: Gemini for extraction

    _cached_settings = LLMProviderSettings(
        intent_provider=os.getenv("INTENT_PROVIDER", default_extraction),
        entity_provider=os.getenv("ENTITY_PROVIDER", default_extraction),
        verbalization_provider=os.getenv("VERBALIZER_PROVIDER", "openai"),
        source="environment",
    )
    return _cached_settings


def clear_provider_cache() -> None:
    """Clear the cached provider settings. Call after config changes."""
    global _cached_settings
    _cached_settings = None


def get_intent_provider() -> Provider:
    """Get the provider for intent classification."""
    return get_llm_providers().intent_provider


def get_entity_provider() -> Provider:
    """Get the provider for entity extraction."""
    return get_llm_providers().entity_provider


def get_verbalization_provider() -> Provider:
    """Get the provider for verbalization/draft composition."""
    return get_llm_providers().verbalization_provider
