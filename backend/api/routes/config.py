"""
MODULE: backend/api/routes/config.py
PURPOSE: Configuration management endpoints.

ENDPOINTS:
    GET  /api/config/global-deposit   - Get global deposit config
    POST /api/config/global-deposit   - Set global deposit config
    GET  /api/config/hil-mode         - Get HIL mode status
    POST /api/config/hil-mode         - Toggle HIL mode (all AI replies require approval)
    GET  /api/config/llm-provider     - Get LLM provider settings
    POST /api/config/llm-provider     - Set LLM provider settings
    GET  /api/config/pre-filter       - Get pre-filter mode (enhanced/legacy)
    POST /api/config/pre-filter       - Set pre-filter mode
    GET  /api/config/detection-mode   - Get detection mode (unified/legacy)
    POST /api/config/detection-mode   - Set detection mode

DEPENDS ON:
    - backend/workflow_email.py  # Database operations
"""

from datetime import datetime
from typing import Dict, List, Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.workflow_email import (
    load_db as wf_load_db,
    save_db as wf_save_db,
)
from backend.ux.universal_verbalizer import (
    UNIVERSAL_SYSTEM_PROMPT,
    STEP_PROMPTS as DEFAULT_STEP_PROMPTS
)


router = APIRouter(prefix="/api/config", tags=["config"])


# --- Request Models ---

class GlobalDepositConfig(BaseModel):
    """
    Global deposit configuration applied to all offers by default.
    """
    deposit_enabled: bool = False
    deposit_type: str = "percentage"  # "percentage" or "fixed"
    deposit_percentage: int = 30
    deposit_fixed_amount: float = 0.0
    deposit_deadline_days: int = 10


class HILModeConfig(BaseModel):
    """
    Human-in-the-Loop mode configuration.

    When enabled, ALL AI-generated replies require manager approval before
    being sent to clients. This is the recommended setting for production
    environments during initial deployment.

    MANAGER WORKFLOW:
    1. AI generates a reply draft
    2. Draft appears in "AI Reply Approval" queue (separate from client tasks)
    3. Manager reviews, optionally edits the message
    4. Manager approves → message sent to client
    5. Manager rejects → message discarded, no client notification

    USE CASES:
    - Production launch: Enable to review all AI outputs
    - Gradual trust building: Monitor AI quality before full automation
    - Compliance: Ensure human review of all client communications
    """
    enabled: bool


class LLMProviderConfig(BaseModel):
    """
    LLM provider configuration for per-operation routing.

    Allows selecting different providers for different operations:
    - intent: Provider for intent classification (gemini = 75% cheaper)
    - entity: Provider for entity extraction (gemini = 75% cheaper)
    - verbalization: Provider for draft composition (openai = better quality)

    Valid providers: "openai", "gemini", "stub"

    Defaults: Hybrid mode (Gemini for extraction, OpenAI for verbalization)
    """
    intent_provider: str = "gemini"       # Default: cheap, good accuracy
    entity_provider: str = "gemini"       # Default: cheap, structured extraction
    verbalization_provider: str = "openai"  # Default: quality for client-facing


class PreFilterConfig(BaseModel):
    """
    Pre-filter mode configuration for per-message detection.

    The pre-filter runs on EVERY message to detect signals before LLM calls.
    This allows skipping unnecessary LLM calls and routing special cases.

    Modes:
    - "enhanced": Full keyword detection + signal flags (can skip LLM calls)
    - "legacy": Basic duplicate detection only (always runs LLM)

    Toggle this to fall back to regex-only if enhanced mode causes issues.
    """
    mode: str = "legacy"  # Default: safe legacy mode


class DetectionModeConfig(BaseModel):
    """
    Detection mode configuration - unified vs legacy detection pipeline.

    Modes:
    - "unified": ONE LLM call per message that extracts intent + signals + entities
                 (~$0.004/msg with Gemini, more accurate, no false positives)
    - "legacy": Separate keyword pre-filter + intent LLM + entity LLM calls
                (~$0.013/msg, can have regex false positives)

    Use unified mode for best accuracy and cost savings.
    Fall back to legacy if unified mode causes issues.
    """
    mode: str = "unified"  # Default: unified mode (recommended)


class PromptConfig(BaseModel):
    """
    Configuration for LLM prompts (System + Per-Step).
    Used by the "River" configuration page.
    """
    system_prompt: str
    step_prompts: Dict[int, str]


class PromptHistoryEntry(BaseModel):
    ts: str
    config: PromptConfig


class PromptHistoryResponse(BaseModel):
    history: List[PromptHistoryEntry]


# --- Helper Functions ---

def _now_iso() -> str:
    """Return current UTC time in ISO format."""
    return datetime.utcnow().isoformat() + "Z"


# --- Route Handlers ---

@router.get("/global-deposit")
async def get_global_deposit_config():
    """
    Get the current global deposit configuration.

    Returns default values if not yet configured.
    """
    try:
        db = wf_load_db()
        config = db.get("config", {}).get("global_deposit", {})
        return {
            "deposit_enabled": config.get("deposit_enabled", False),
            "deposit_type": config.get("deposit_type", "percentage"),
            "deposit_percentage": config.get("deposit_percentage", 30),
            "deposit_fixed_amount": config.get("deposit_fixed_amount", 0.0),
            "deposit_deadline_days": config.get("deposit_deadline_days", 10),
        }
    except Exception as exc:
        raise HTTPException(
            status_code=500, detail=f"Failed to load deposit config: {exc}"
        ) from exc


@router.post("/global-deposit")
async def set_global_deposit_config(config: GlobalDepositConfig):
    """
    Set the global deposit configuration.

    This setting applies to all offers unless overridden by room-specific
    deposit settings (future feature).
    """
    try:
        db = wf_load_db()
        if "config" not in db:
            db["config"] = {}
        db["config"]["global_deposit"] = {
            "deposit_enabled": config.deposit_enabled,
            "deposit_type": config.deposit_type,
            "deposit_percentage": config.deposit_percentage,
            "deposit_fixed_amount": config.deposit_fixed_amount,
            "deposit_deadline_days": config.deposit_deadline_days,
            "updated_at": _now_iso(),
        }
        wf_save_db(db)
        print(f"[Config] Global deposit updated: enabled={config.deposit_enabled} type={config.deposit_type}")
        return {"status": "ok", "config": db["config"]["global_deposit"]}
    except Exception as exc:
        raise HTTPException(
            status_code=500, detail=f"Failed to save deposit config: {exc}"
        ) from exc


# ---------------------------------------------------------------------------
# HIL Mode Configuration Endpoints
# ---------------------------------------------------------------------------

@router.get("/hil-mode")
async def get_hil_mode():
    """
    Get the current HIL (Human-in-the-Loop) mode status.

    When enabled, ALL AI-generated replies require manager approval before
    being sent to clients.

    Priority order:
    1. Database setting (if set) - allows runtime toggle
    2. Environment variable OE_HIL_ALL_LLM_REPLIES - server default
    3. False (disabled) - backwards compatible default

    Returns:
        enabled: bool - Whether HIL mode is active
        source: str - Where the setting came from ("database", "environment", "default")
    """
    try:
        db = wf_load_db()
        hil_config = db.get("config", {}).get("hil_mode", {})

        # Check database first
        if "enabled" in hil_config:
            return {
                "enabled": hil_config["enabled"],
                "source": "database",
                "updated_at": hil_config.get("updated_at"),
            }

        # Fall back to environment variable
        import os
        env_value = os.getenv("OE_HIL_ALL_LLM_REPLIES", "").lower()
        if env_value in ("true", "1", "yes"):
            return {"enabled": True, "source": "environment"}
        elif env_value in ("false", "0", "no"):
            return {"enabled": False, "source": "environment"}

        # Default
        return {"enabled": False, "source": "default"}

    except Exception as exc:
        raise HTTPException(
            status_code=500, detail=f"Failed to load HIL mode config: {exc}"
        ) from exc


@router.post("/hil-mode")
async def set_hil_mode(config: HILModeConfig):
    """
    Toggle HIL (Human-in-the-Loop) mode for AI replies.

    When enabled:
    - ALL AI-generated replies go to "AI Reply Approval" queue
    - Manager must approve each reply before it's sent to client
    - Manager can edit the reply before approving

    When disabled:
    - AI replies are sent directly to clients (current behavior)
    - Only specific workflow actions require HIL approval

    This setting persists in the database and takes effect immediately.
    It overrides the OE_HIL_ALL_LLM_REPLIES environment variable.
    """
    try:
        db = wf_load_db()
        if "config" not in db:
            db["config"] = {}

        db["config"]["hil_mode"] = {
            "enabled": config.enabled,
            "updated_at": _now_iso(),
        }
        wf_save_db(db)

        # Notify the integration config module to refresh
        from backend.workflows.io.integration.config import refresh_hil_setting
        refresh_hil_setting()

        status = "enabled" if config.enabled else "disabled"
        print(f"[Config] HIL mode {status} - all AI replies {'require' if config.enabled else 'do not require'} manager approval")

        return {
            "status": "ok",
            "enabled": config.enabled,
            "message": f"HIL mode {status}. {'All AI replies now require manager approval.' if config.enabled else 'AI replies will be sent directly to clients.'}",
        }
    except Exception as exc:
        raise HTTPException(
            status_code=500, detail=f"Failed to save HIL mode config: {exc}"
        ) from exc


# ---------------------------------------------------------------------------
# LLM Provider Configuration Endpoints
# ---------------------------------------------------------------------------

VALID_PROVIDERS = {"openai", "gemini", "stub"}


@router.get("/llm-provider")
async def get_llm_provider_config():
    """
    Get the current LLM provider configuration.

    Returns provider settings for each operation type:
    - intent_provider: For intent classification
    - entity_provider: For entity extraction
    - verbalization_provider: For draft composition

    Priority order:
    1. Database setting (if set) - allows runtime toggle via admin UI
    2. Environment variables (INTENT_PROVIDER, ENTITY_PROVIDER, VERBALIZER_PROVIDER)
    3. AGENT_MODE environment variable - sets all operations to same provider
    4. "openai" - default fallback

    Returns:
        intent_provider, entity_provider, verbalization_provider: str
        source: str - Where the settings came from
    """
    import os

    try:
        db = wf_load_db()
        llm_config = db.get("config", {}).get("llm_provider", {})

        # Check database first
        if llm_config.get("intent_provider") or llm_config.get("entity_provider"):
            return {
                "intent_provider": llm_config.get("intent_provider", "openai"),
                "entity_provider": llm_config.get("entity_provider", "openai"),
                "verbalization_provider": llm_config.get("verbalization_provider", "openai"),
                "source": "database",
                "updated_at": llm_config.get("updated_at"),
            }

        # Fall back to environment variables
        # Default: Hybrid mode (Gemini for extraction, OpenAI for verbalization)
        agent_mode = os.getenv("AGENT_MODE", "gemini").lower()
        intent_provider = os.getenv("INTENT_PROVIDER", agent_mode)
        entity_provider = os.getenv("ENTITY_PROVIDER", agent_mode)
        verbalization_provider = os.getenv("VERBALIZER_PROVIDER", "openai")

        return {
            "intent_provider": intent_provider,
            "entity_provider": entity_provider,
            "verbalization_provider": verbalization_provider,
            "source": "environment",
        }

    except Exception as exc:
        raise HTTPException(
            status_code=500, detail=f"Failed to load LLM provider config: {exc}"
        ) from exc


@router.post("/llm-provider")
async def set_llm_provider_config(config: LLMProviderConfig):
    """
    Set the LLM provider configuration.

    Allows selecting different providers for different operations:
    - intent_provider: gemini = 75% cheaper, good accuracy
    - entity_provider: gemini = 75% cheaper, good for structured extraction
    - verbalization_provider: openai recommended for quality-critical drafts

    Valid providers: "openai", "gemini", "stub"

    This setting persists in the database and takes effect on next request.
    It overrides environment variables.

    COST COMPARISON:
    | Operation | OpenAI (o3-mini) | Gemini Flash | Savings |
    |-----------|------------------|--------------|---------|
    | Intent    | ~$0.005          | ~$0.00125    | 75%     |
    | Entity    | ~$0.008          | ~$0.002      | 75%     |
    | Verbalize | ~$0.015          | ~$0.004      | 73%     |
    """
    import os

    # Validate providers
    for field, value in [
        ("intent_provider", config.intent_provider),
        ("entity_provider", config.entity_provider),
        ("verbalization_provider", config.verbalization_provider),
    ]:
        if value.lower() not in VALID_PROVIDERS:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid {field}: '{value}'. Must be one of: {', '.join(VALID_PROVIDERS)}"
            )

    try:
        db = wf_load_db()
        if "config" not in db:
            db["config"] = {}

        db["config"]["llm_provider"] = {
            "intent_provider": config.intent_provider.lower(),
            "entity_provider": config.entity_provider.lower(),
            "verbalization_provider": config.verbalization_provider.lower(),
            "updated_at": _now_iso(),
        }
        wf_save_db(db)

        # Update environment variables for current process
        # (takes effect on next adapter instantiation)
        os.environ["INTENT_PROVIDER"] = config.intent_provider.lower()
        os.environ["ENTITY_PROVIDER"] = config.entity_provider.lower()
        os.environ["VERBALIZER_PROVIDER"] = config.verbalization_provider.lower()

        # Reset caches to pick up new settings
        from backend.adapters.agent_adapter import reset_agent_adapter
        from backend.llm.provider_config import clear_provider_cache
        reset_agent_adapter()
        clear_provider_cache()

        print(f"[Config] LLM providers updated: intent={config.intent_provider} entity={config.entity_provider} verbalization={config.verbalization_provider}")

        return {
            "status": "ok",
            "intent_provider": config.intent_provider.lower(),
            "entity_provider": config.entity_provider.lower(),
            "verbalization_provider": config.verbalization_provider.lower(),
            "message": "LLM provider settings updated. Changes take effect on next request.",
        }
    except Exception as exc:
        raise HTTPException(
            status_code=500, detail=f"Failed to save LLM provider config: {exc}"
        ) from exc


# ---------------------------------------------------------------------------
# Prompt Configuration Endpoints
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Pre-Filter Configuration Endpoints
# ---------------------------------------------------------------------------

VALID_PRE_FILTER_MODES = {"enhanced", "legacy"}


@router.get("/pre-filter")
async def get_pre_filter_config():
    """
    Get the current pre-filter mode configuration.

    Pre-filter runs on EVERY message before LLM calls to detect:
    - Duplicate messages
    - Language
    - Confirmation/acceptance/rejection signals
    - Manager escalation requests
    - Billing address patterns
    - Urgency markers

    Modes:
    - "enhanced": Full keyword detection, can skip unnecessary LLM calls
    - "legacy": Basic duplicate detection only, always runs LLM (safe fallback)

    Priority order:
    1. Database setting (if set) - allows runtime toggle via admin UI
    2. Environment variable PRE_FILTER_MODE
    3. "legacy" - safe default

    Returns:
        mode: str - Current pre-filter mode
        source: str - Where the setting came from
    """
    import os

    try:
        db = wf_load_db()
        pre_filter_config = db.get("config", {}).get("pre_filter", {})

        # Check database first
        if pre_filter_config.get("mode"):
            return {
                "mode": pre_filter_config["mode"],
                "source": "database",
                "updated_at": pre_filter_config.get("updated_at"),
            }

        # Fall back to environment variable
        env_mode = os.getenv("PRE_FILTER_MODE", "legacy").lower()
        if env_mode in VALID_PRE_FILTER_MODES:
            return {"mode": env_mode, "source": "environment"}

        # Default
        return {"mode": "legacy", "source": "default"}

    except Exception as exc:
        raise HTTPException(
            status_code=500, detail=f"Failed to load pre-filter config: {exc}"
        ) from exc


@router.post("/pre-filter")
async def set_pre_filter_config(config: PreFilterConfig):
    """
    Set the pre-filter mode configuration.

    Toggle between enhanced and legacy modes for per-message detection:
    - "enhanced": Full keyword detection with LLM skip optimization
    - "legacy": Safe fallback, basic duplicate detection only

    Use "legacy" mode if enhanced mode causes false positives or issues.
    Switch to "enhanced" once confident in keyword detection accuracy.

    COST IMPACT:
    - Legacy: Always runs intent LLM (~$0.005/msg)
    - Enhanced: Can skip ~25% of intent LLM calls (saves ~$0.00125/msg)

    This setting persists in the database and takes effect immediately.
    """
    import os

    # Validate mode
    if config.mode.lower() not in VALID_PRE_FILTER_MODES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid mode: '{config.mode}'. Must be one of: {', '.join(VALID_PRE_FILTER_MODES)}"
        )

    try:
        db = wf_load_db()
        if "config" not in db:
            db["config"] = {}

        db["config"]["pre_filter"] = {
            "mode": config.mode.lower(),
            "updated_at": _now_iso(),
        }
        wf_save_db(db)

        # Update environment variable for current process
        os.environ["PRE_FILTER_MODE"] = config.mode.lower()

        print(f"[Config] Pre-filter mode updated: {config.mode}")

        return {
            "status": "ok",
            "mode": config.mode.lower(),
            "message": f"Pre-filter mode set to '{config.mode}'. "
                      f"{'Full keyword detection enabled.' if config.mode == 'enhanced' else 'Safe legacy mode, always runs LLM.'}",
        }
    except Exception as exc:
        raise HTTPException(
            status_code=500, detail=f"Failed to save pre-filter config: {exc}"
        ) from exc


# ---------------------------------------------------------------------------
# Detection Mode Configuration Endpoints
# ---------------------------------------------------------------------------

VALID_DETECTION_MODES = {"unified", "legacy"}


@router.get("/detection-mode")
async def get_detection_mode_config():
    """
    Get the current detection mode configuration.

    Detection mode controls how messages are analyzed:
    - "unified": ONE LLM call for intent + signals + entities (~$0.004/msg)
    - "legacy": Separate keyword + intent + entity calls (~$0.013/msg)

    Priority order:
    1. Database setting (if set) - allows runtime toggle via admin UI
    2. Environment variable DETECTION_MODE
    3. "unified" - recommended default

    Returns:
        mode: str - Current detection mode
        source: str - Where the setting came from
    """
    import os

    try:
        db = wf_load_db()
        detection_config = db.get("config", {}).get("detection_mode", {})

        # Check database first
        if detection_config.get("mode"):
            return {
                "mode": detection_config["mode"],
                "source": "database",
                "updated_at": detection_config.get("updated_at"),
            }

        # Fall back to environment variable
        env_mode = os.getenv("DETECTION_MODE", "unified").lower()
        if env_mode in VALID_DETECTION_MODES:
            return {"mode": env_mode, "source": "environment"}

        # Default
        return {"mode": "unified", "source": "default"}

    except Exception as exc:
        raise HTTPException(
            status_code=500, detail=f"Failed to load detection mode config: {exc}"
        ) from exc


@router.post("/detection-mode")
async def set_detection_mode_config(config: DetectionModeConfig):
    """
    Set the detection mode configuration.

    Toggle between unified and legacy detection pipelines:
    - "unified": ONE LLM call for everything (~$0.004/msg, recommended)
    - "legacy": Separate calls (keyword + intent + entity)

    COST COMPARISON:
    | Mode    | Cost/msg | Accuracy | Notes                        |
    |---------|----------|----------|------------------------------|
    | unified | $0.004   | High     | Single Gemini call, no regex |
    | legacy  | $0.013   | Medium   | Regex can have false pos     |

    This setting persists in the database and takes effect immediately.
    """
    import os

    # Validate mode
    if config.mode.lower() not in VALID_DETECTION_MODES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid mode: '{config.mode}'. Must be one of: {', '.join(VALID_DETECTION_MODES)}"
        )

    try:
        db = wf_load_db()
        if "config" not in db:
            db["config"] = {}

        db["config"]["detection_mode"] = {
            "mode": config.mode.lower(),
            "updated_at": _now_iso(),
        }
        wf_save_db(db)

        # Update environment variable for current process
        os.environ["DETECTION_MODE"] = config.mode.lower()

        print(f"[Config] Detection mode updated: {config.mode}")

        return {
            "status": "ok",
            "mode": config.mode.lower(),
            "message": f"Detection mode set to '{config.mode}'. "
                      f"{'One LLM call per message (recommended).' if config.mode == 'unified' else 'Separate keyword + intent + entity calls.'}",
        }
    except Exception as exc:
        raise HTTPException(
            status_code=500, detail=f"Failed to save detection mode config: {exc}"
        ) from exc


# ---------------------------------------------------------------------------
# Prompt Configuration Endpoints
# ---------------------------------------------------------------------------

@router.get("/prompts", response_model=PromptConfig)
async def get_prompts_config():
    """
    Get current prompt configuration.
    Merges DB overrides with code defaults.
    """
    try:
        db = wf_load_db()
        stored = db.get("config", {}).get("prompts", {})
        
        # Merge stored steps with defaults to ensure all keys exist
        merged_steps = DEFAULT_STEP_PROMPTS.copy()
        stored_steps = stored.get("step_prompts", {})
        
        # stored_steps keys might be strings in JSON, convert to int for merging
        for k, v in stored_steps.items():
            try:
                merged_steps[int(k)] = v
            except ValueError:
                pass

        return {
            "system_prompt": stored.get("system_prompt", UNIVERSAL_SYSTEM_PROMPT),
            "step_prompts": merged_steps
        }
    except Exception as exc:
        print(f"[Config][ERROR] Failed to load prompts: {exc}")
        # Fallback to defaults on error
        return {
            "system_prompt": UNIVERSAL_SYSTEM_PROMPT,
            "step_prompts": DEFAULT_STEP_PROMPTS
        }


@router.post("/prompts")
async def set_prompts_config(config: PromptConfig):
    """
    Save new prompt configuration.
    Archives the previous version to history.
    """
    try:
        db = wf_load_db()
        if "config" not in db:
            db["config"] = {}
        
        # Archive current state if exists
        current = db["config"].get("prompts")
        if current:
            history = db["config"].get("prompts_history", [])
            history.insert(0, {
                "ts": _now_iso(),
                "config": current
            })
            # Keep history limited (e.g. last 50 versions)
            db["config"]["prompts_history"] = history[:50]
        
        # Save new state
        db["config"]["prompts"] = {
            "system_prompt": config.system_prompt,
            "step_prompts": {str(k): v for k, v in config.step_prompts.items()},
            "updated_at": _now_iso()
        }
        wf_save_db(db)
        print("[Config] Prompts updated and persisted.")
        return {"status": "ok"}
    except Exception as exc:
        raise HTTPException(
            status_code=500, detail=f"Failed to save prompts: {exc}"
        ) from exc


@router.get("/prompts/history", response_model=PromptHistoryResponse)
async def get_prompts_history():
    """Get the history of prompt changes."""
    try:
        db = wf_load_db()
        history = db.get("config", {}).get("prompts_history", [])
        return {"history": history}
    except Exception as exc:
        raise HTTPException(
            status_code=500, detail=f"Failed to load prompt history: {exc}"
        ) from exc


@router.post("/prompts/revert/{index}")
async def revert_prompts_config(index: int):
    """
    Revert prompt configuration to a historical version.
    The current state is pushed to history before reverting.
    """
    try:
        db = wf_load_db()
        history = db.get("config", {}).get("prompts_history", [])
        
        if index < 0 or index >= len(history):
            raise HTTPException(status_code=404, detail="History index out of range")
            
        target_entry = history[index]
        target_config = target_entry.get("config")
        
        if not target_config:
            raise HTTPException(status_code=400, detail="Invalid history entry")

        # Archive current
        current = db["config"].get("prompts")
        if current:
            history.insert(0, {
                "ts": _now_iso(),
                "config": current
            })
            
        # Apply revert
        db["config"]["prompts"] = target_config
        db["config"]["prompts"]["updated_at"] = _now_iso()
        
        # Update history
        db["config"]["prompts_history"] = history[:50]
        
        wf_save_db(db)
        print(f"[Config] Reverted prompts to version from {target_entry.get('ts')}")
        return {"status": "ok"}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=500, detail=f"Failed to revert prompts: {exc}"
        ) from exc



# ---------------------------------------------------------------------------
# Room-Specific Deposit Endpoints (INACTIVE - For Future Integration)
# ---------------------------------------------------------------------------
# INTEGRATION NOTE FOR FRONTEND INTEGRATORS:
# ==========================================
# These endpoints are prepared for future integration with the main OpenEvent
# frontend. They allow setting deposit requirements per room, which override
# the global deposit setting.
#
# To activate:
# 1. Uncomment the endpoints below
# 2. Add the corresponding UI in the Rooms Setup page
# 3. Update the offer generation logic to check room-specific deposits first
#
# Data structure (stored in db.config.room_deposits[room_id]):
# {
#   "deposit_required": boolean,
#   "deposit_percent": number (1-100),
#   "updated_at": ISO timestamp
# }
# ---------------------------------------------------------------------------

# @router.get("/room-deposit/{room_id}")
# async def get_room_deposit_config(room_id: str):
#     """
#     Get deposit configuration for a specific room.
#
#     INACTIVE - Uncomment when integrating with main frontend.
#     """
#     try:
#         db = wf_load_db()
#         room_deposits = db.get("config", {}).get("room_deposits", {})
#         config = room_deposits.get(room_id, {})
#         return {
#             "room_id": room_id,
#             "deposit_required": config.get("deposit_required", False),
#             "deposit_percent": config.get("deposit_percent", None),
#             "updated_at": config.get("updated_at"),
#         }
#     except Exception as exc:
#         raise HTTPException(
#             status_code=500, detail=f"Failed to load room deposit config: {exc}"
#         ) from exc
#
#
# @router.post("/room-deposit/{room_id}")
# async def set_room_deposit_config(room_id: str, deposit_required: bool, deposit_percent: Optional[int] = None):
#     """
#     Set deposit configuration for a specific room.
#
#     INACTIVE - Uncomment when integrating with main frontend.
#
#     This overrides the global deposit setting for offers using this room.
#     """
#     try:
#         db = wf_load_db()
#         if "config" not in db:
#             db["config"] = {}
#         if "room_deposits" not in db["config"]:
#             db["config"]["room_deposits"] = {}
#         db["config"]["room_deposits"][room_id] = {
#             "deposit_required": deposit_required,
#             "deposit_percent": deposit_percent,
#             "updated_at": _now_iso(),
#         }
#         wf_save_db(db)
#         print(f"[Config] Room deposit updated: room={room_id} required={deposit_required} percent={deposit_percent}")
#         return {"status": "ok", "room_id": room_id, "config": db["config"]["room_deposits"][room_id]}
#     except Exception as exc:
#         raise HTTPException(
#             status_code=500, detail=f"Failed to save room deposit config: {exc}"
#         ) from exc


# ---------------------------------------------------------------------------
# HIL Email Notification Configuration
# ---------------------------------------------------------------------------

class HILEmailConfig(BaseModel):
    """
    HIL email notification configuration.

    When enabled, sends email notifications to the Event Manager
    when HIL tasks are created (in addition to the frontend panel).

    PRODUCTION NOTE:
    The manager_email should come from Supabase auth (logged-in user).
    This config serves as a fallback or for testing environments.
    """
    enabled: bool = False
    manager_email: Optional[str] = None  # Fallback; production uses Supabase auth
    smtp_host: Optional[str] = None
    smtp_port: Optional[int] = None
    smtp_user: Optional[str] = None
    from_email: Optional[str] = None


@router.get("/hil-email")
async def get_hil_email_config():
    """
    Get the current HIL email notification configuration.

    HIL email notifications send emails to the Event Manager when
    tasks require approval. This works IN ADDITION to the frontend
    Manager Tasks panel.

    Returns:
        enabled: bool - Whether email notifications are active
        manager_email: str - Email to notify (from config or Supabase)
        smtp_configured: bool - Whether SMTP is ready
        source: str - Where the config came from
    """
    try:
        from backend.services.hil_email_notification import get_hil_email_config as get_email_config
        config = get_email_config()

        return {
            "enabled": config["enabled"],
            "manager_email": config["manager_email"],
            "smtp_configured": bool(config["smtp_user"] and config["smtp_password"]),
            "smtp_host": config["smtp_host"],
            "from_email": config["from_email"],
            "source": "database" if config["manager_email"] else "environment",
        }
    except Exception as exc:
        raise HTTPException(
            status_code=500, detail=f"Failed to load HIL email config: {exc}"
        ) from exc


@router.post("/hil-email")
async def set_hil_email_config(config: HILEmailConfig):
    """
    Set the HIL email notification configuration.

    Enable email notifications when HIL tasks are created:
    - enabled: Toggle email notifications
    - manager_email: Email to receive notifications

    SMTP settings can also be configured here, or via environment:
    - SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD
    - HIL_FROM_EMAIL, HIL_FROM_NAME

    PRODUCTION NOTE:
    In production, manager_email should come from Supabase auth
    (the logged-in Event Manager). This endpoint is for testing
    or as a fallback.
    """
    try:
        db = wf_load_db()
        if "config" not in db:
            db["config"] = {}

        hil_email_data = {
            "enabled": config.enabled,
            "updated_at": _now_iso(),
        }

        if config.manager_email:
            hil_email_data["manager_email"] = config.manager_email
        if config.smtp_host:
            hil_email_data["smtp_host"] = config.smtp_host
        if config.smtp_port:
            hil_email_data["smtp_port"] = config.smtp_port
        if config.smtp_user:
            hil_email_data["smtp_user"] = config.smtp_user
        if config.from_email:
            hil_email_data["from_email"] = config.from_email

        db["config"]["hil_email"] = hil_email_data
        wf_save_db(db)

        status = "enabled" if config.enabled else "disabled"
        print(f"[Config] HIL email {status} - notifications to {config.manager_email}")

        return {
            "status": "ok",
            "enabled": config.enabled,
            "manager_email": config.manager_email,
            "message": f"HIL email notifications {status}."
                      + (f" Notifications will be sent to {config.manager_email}" if config.enabled else ""),
        }
    except Exception as exc:
        raise HTTPException(
            status_code=500, detail=f"Failed to save HIL email config: {exc}"
        ) from exc


@router.post("/hil-email/test")
async def test_hil_email():
    """
    Send a test HIL email notification.

    Use this to verify email configuration is working correctly.
    """
    try:
        from backend.services.hil_email_notification import (
            is_hil_email_enabled,
            send_hil_notification,
        )

        if not is_hil_email_enabled():
            return {
                "success": False,
                "error": "HIL email not enabled. Configure via POST /api/config/hil-email first.",
            }

        result = send_hil_notification(
            task_id="test-" + _now_iso().replace(":", "-"),
            task_type="test_notification",
            client_name="Test Client",
            client_email="test@example.com",
            draft_body="This is a test HIL notification.\n\nIf you received this, email notifications are working correctly!",
            event_summary={
                "chosen_date": "2026-01-15",
                "locked_room": "Test Room",
                "offer_total": 1500.00,
            },
        )

        return result

    except Exception as exc:
        raise HTTPException(
            status_code=500, detail=f"Failed to send test email: {exc}"
        ) from exc
