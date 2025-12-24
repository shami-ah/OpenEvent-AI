"""
Integration configuration with toggle switch.

Toggle between JSON-based storage (current) and Supabase (integration).

Usage:
    # Check current mode
    from backend.workflows.io.integration import is_integration_mode

    if is_integration_mode():
        # Use Supabase adapter
    else:
        # Use JSON file adapter (current behavior)

Environment Variables:
    OE_INTEGRATION_MODE: Set to "supabase" to enable integration mode
    OE_SUPABASE_URL: Supabase project URL (required in integration mode)
    OE_SUPABASE_KEY: Supabase anon/service key (required in integration mode)
    OE_TEAM_ID: Team UUID for multi-tenant operations
    OE_SYSTEM_USER_ID: System user UUID for automated writes
    OE_EMAIL_ACCOUNT_ID: Email account UUID for email operations
    OE_HIL_ALL_LLM_REPLIES: Set to "true" to require HIL approval for all AI replies
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class IntegrationConfig:
    """Configuration for Supabase integration."""

    # Toggle: "json" (current) or "supabase" (integration)
    mode: str = "json"

    # Supabase connection (only used when mode="supabase")
    supabase_url: Optional[str] = None
    supabase_key: Optional[str] = None

    # Multi-tenant identifiers (required for Supabase mode)
    team_id: Optional[str] = None
    system_user_id: Optional[str] = None
    email_account_id: Optional[str] = None

    # Feature flags for gradual rollout
    use_supabase_clients: bool = False  # Use Supabase for client lookup
    use_supabase_events: bool = False   # Use Supabase for event storage
    use_supabase_tasks: bool = False    # Use Supabase for HIL tasks
    use_supabase_emails: bool = False   # Use Supabase for email storage

    # HIL for all LLM replies (default OFF for backwards compatibility)
    # When True: ALL AI-generated outbound replies go to "AI Reply Approval" HIL queue
    # When False: Current behavior (only specific actions require HIL)
    # TODO: Set to True when integrating with OpenEvent frontend for full manager control
    hil_all_llm_replies: bool = False

    @classmethod
    def from_env(cls) -> "IntegrationConfig":
        """Load configuration from environment variables."""
        mode = os.getenv("OE_INTEGRATION_MODE", "json").lower()
        hil_all_replies = os.getenv("OE_HIL_ALL_LLM_REPLIES", "false").lower() in ("true", "1", "yes")

        return cls(
            mode=mode,
            supabase_url=os.getenv("OE_SUPABASE_URL"),
            supabase_key=os.getenv("OE_SUPABASE_KEY"),
            team_id=os.getenv("OE_TEAM_ID"),
            system_user_id=os.getenv("OE_SYSTEM_USER_ID"),
            email_account_id=os.getenv("OE_EMAIL_ACCOUNT_ID"),
            # Feature flags default to True in supabase mode
            use_supabase_clients=mode == "supabase",
            use_supabase_events=mode == "supabase",
            use_supabase_tasks=mode == "supabase",
            use_supabase_emails=mode == "supabase",
            # HIL toggle for all LLM replies
            hil_all_llm_replies=hil_all_replies,
        )

    def is_supabase_mode(self) -> bool:
        """Check if running in Supabase integration mode."""
        return self.mode == "supabase"

    def validate(self) -> list[str]:
        """Validate configuration, return list of errors."""
        errors = []

        if self.mode == "supabase":
            if not self.supabase_url:
                errors.append("OE_SUPABASE_URL is required in supabase mode")
            if not self.supabase_key:
                errors.append("OE_SUPABASE_KEY is required in supabase mode")
            if not self.team_id:
                errors.append("OE_TEAM_ID is required in supabase mode")
            if not self.system_user_id:
                errors.append("OE_SYSTEM_USER_ID is required in supabase mode")

        return errors


# Global config instance - loaded once at module import
INTEGRATION_CONFIG = IntegrationConfig.from_env()


def is_integration_mode() -> bool:
    """Quick check if running in Supabase integration mode."""
    return INTEGRATION_CONFIG.is_supabase_mode()


def get_team_id() -> Optional[str]:
    """Get the configured team_id for multi-tenant operations."""
    return INTEGRATION_CONFIG.team_id


def get_system_user_id() -> Optional[str]:
    """Get the configured system_user_id for automated writes."""
    return INTEGRATION_CONFIG.system_user_id


def reload_config() -> None:
    """Reload configuration from environment (useful for testing)."""
    global INTEGRATION_CONFIG
    INTEGRATION_CONFIG = IntegrationConfig.from_env()


def _get_hil_setting_from_db() -> Optional[bool]:
    """Check database for HIL mode setting (allows runtime toggle).

    Returns None if not set in database, otherwise the boolean value.
    """
    try:
        # Import here to avoid circular dependency
        from backend.workflow_email import load_db as wf_load_db
        db = wf_load_db()
        hil_config = db.get("config", {}).get("hil_mode", {})
        if "enabled" in hil_config:
            return hil_config["enabled"]
    except Exception as exc:
        # Database not available or error - fall back to env var
        print(f"[Config][WARN] Could not read HIL setting from DB: {exc}")
    return None


# Cache for HIL setting to avoid repeated DB reads
_hil_setting_cache: Optional[bool] = None


def refresh_hil_setting() -> None:
    """Refresh HIL setting from database. Call after POST /api/config/hil-mode."""
    global _hil_setting_cache
    _hil_setting_cache = _get_hil_setting_from_db()


def is_hil_all_replies_enabled() -> bool:
    """Check if HIL approval is required for all AI replies.

    Priority order:
    1. Database setting (if set) - allows runtime toggle via API
    2. Environment variable OE_HIL_ALL_LLM_REPLIES - server default
    3. False - backwards compatible default

    When True: ALL AI-generated outbound replies go to "AI Reply Approval" queue
    When False: Current behavior (only specific actions require HIL approval)
    """
    global _hil_setting_cache

    # Check cache first (set by refresh_hil_setting after API calls)
    if _hil_setting_cache is not None:
        return _hil_setting_cache

    # Check database (first call or cache invalidated)
    db_setting = _get_hil_setting_from_db()
    if db_setting is not None:
        _hil_setting_cache = db_setting
        return db_setting

    # Fall back to environment variable / config
    return INTEGRATION_CONFIG.hil_all_llm_replies