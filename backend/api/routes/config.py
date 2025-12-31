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
    GET  /api/config/venue            - Get venue settings (name, city, timezone, etc.)
    POST /api/config/venue            - Set venue settings
    GET  /api/config/site-visit       - Get site visit settings (blocked dates, slots, weekday rules)
    POST /api/config/site-visit       - Set site visit settings
    GET  /api/config/managers         - Get manager settings (names for escalation)
    POST /api/config/managers         - Set manager settings
    GET  /api/config/products         - Get product settings (autofill threshold)
    POST /api/config/products         - Set product settings
    GET  /api/config/menus            - Get menus (catering) settings
    POST /api/config/menus            - Set menus (catering) settings
    GET  /api/config/catalog          - Get catalog settings (product-room availability)
    POST /api/config/catalog          - Set catalog settings
    GET  /api/config/faq              - Get FAQ settings
    POST /api/config/faq              - Set FAQ settings

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
    STEP_PROMPTS as DEFAULT_STEP_PROMPTS,
    _build_system_prompt as build_dynamic_system_prompt,
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

        # Use dynamic prompt with venue config as the default
        default_prompt = build_dynamic_system_prompt()
        return {
            "system_prompt": stored.get("system_prompt") or default_prompt,
            "step_prompts": merged_steps
        }
    except Exception as exc:
        print(f"[Config][ERROR] Failed to load prompts: {exc}")
        # Fallback to dynamic defaults on error
        return {
            "system_prompt": build_dynamic_system_prompt(),
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


# ---------------------------------------------------------------------------
# Venue Configuration Endpoints
# ---------------------------------------------------------------------------

class OperatingHoursConfig(BaseModel):
    """Operating hours configuration."""
    start: int = 8
    end: int = 23


class VenueConfig(BaseModel):
    """
    Venue configuration for multi-tenant / white-label deployments.

    These settings replace previously hardcoded values throughout the codebase:
    - name: Venue name displayed in prompts and emails
    - city: Venue city for location context
    - timezone: IANA timezone (e.g., 'Europe/Zurich')
    - currency_code: ISO currency code (e.g., 'CHF', 'EUR', 'USD')
    - operating_hours: Start/end hours for event availability
    - from_email: Sender email for notifications
    - from_name: Sender name for email headers
    - frontend_url: Base URL for approval links in emails
    """
    name: Optional[str] = None
    city: Optional[str] = None
    timezone: Optional[str] = None
    currency_code: Optional[str] = None
    operating_hours: Optional[OperatingHoursConfig] = None
    from_email: Optional[str] = None
    from_name: Optional[str] = None
    frontend_url: Optional[str] = None


@router.get("/venue")
async def get_venue_config():
    """
    Get the current venue configuration.

    Returns all venue settings with defaults for any missing values.
    These settings control:
    - Venue branding (name, city) in prompts and emails
    - Timezone for date/time handling
    - Currency for pricing display
    - Operating hours for availability validation
    - Email sender details
    - Frontend URL for approval links

    Returns:
        Complete venue configuration with source info
    """
    try:
        from backend.workflows.io.config_store import get_all_venue_config

        config = get_all_venue_config()
        return {
            "name": config.get("name"),
            "city": config.get("city"),
            "timezone": config.get("timezone"),
            "currency_code": config.get("currency_code"),
            "operating_hours": config.get("operating_hours"),
            "from_email": config.get("from_email"),
            "from_name": config.get("from_name"),
            "frontend_url": config.get("frontend_url"),
            "source": "database",
        }
    except Exception as exc:
        raise HTTPException(
            status_code=500, detail=f"Failed to load venue config: {exc}"
        ) from exc


@router.post("/venue")
async def set_venue_config(config: VenueConfig):
    """
    Set the venue configuration.

    Update venue settings for multi-tenant or white-label deployments.
    Only provided fields are updated; omitted fields keep their current values.

    PRODUCTION NOTE:
    Changing these settings affects:
    - AI prompt context (venue name, city)
    - Email sender details
    - Currency formatting in offers
    - Timezone for availability checks
    - Operating hours validation

    Changes take effect immediately for new requests.
    """
    try:
        db = wf_load_db()
        if "config" not in db:
            db["config"] = {}

        # Get current venue config or empty dict
        current = db["config"].get("venue", {})

        # Merge updates (only update provided fields)
        if config.name is not None:
            current["name"] = config.name
        if config.city is not None:
            current["city"] = config.city
        if config.timezone is not None:
            current["timezone"] = config.timezone
        if config.currency_code is not None:
            current["currency_code"] = config.currency_code
        if config.operating_hours is not None:
            current["operating_hours"] = {
                "start": config.operating_hours.start,
                "end": config.operating_hours.end,
            }
        if config.from_email is not None:
            current["from_email"] = config.from_email
        if config.from_name is not None:
            current["from_name"] = config.from_name
        if config.frontend_url is not None:
            current["frontend_url"] = config.frontend_url

        current["updated_at"] = _now_iso()
        db["config"]["venue"] = current
        wf_save_db(db)

        print(f"[Config] Venue updated: name={current.get('name')} city={current.get('city')}")

        return {
            "status": "ok",
            "config": current,
            "message": "Venue configuration updated. Changes take effect immediately.",
        }
    except Exception as exc:
        raise HTTPException(
            status_code=500, detail=f"Failed to save venue config: {exc}"
        ) from exc


# ---------------------------------------------------------------------------
# Site Visit Configuration Endpoints
# ---------------------------------------------------------------------------

class SiteVisitConfig(BaseModel):
    """
    Site visit configuration for scheduling venue tours.

    Controls when and how site visits can be booked:
    - blocked_dates: Additional dates to block (holidays, maintenance)
    - default_slots: Available hours for site visits (24-hour format)
    - weekdays_only: Whether to restrict to weekdays only
    - min_days_ahead: Minimum days before event for booking
    """
    blocked_dates: Optional[List[str]] = None
    default_slots: Optional[List[int]] = None
    weekdays_only: Optional[bool] = None
    min_days_ahead: Optional[int] = None


@router.get("/site-visit")
async def get_site_visit_config():
    """
    Get the current site visit configuration.

    Returns settings for site visit scheduling:
    - blocked_dates: Additional blocked dates (ISO format)
    - default_slots: Available hours [10, 14, 16]
    - weekdays_only: True = Mon-Fri only
    - min_days_ahead: Minimum days before event
    """
    try:
        from backend.workflows.io.config_store import get_all_site_visit_config

        config = get_all_site_visit_config()
        return {
            "blocked_dates": config.get("blocked_dates", []),
            "default_slots": config.get("default_slots", [10, 14, 16]),
            "weekdays_only": config.get("weekdays_only", True),
            "min_days_ahead": config.get("min_days_ahead", 2),
            "source": "database",
        }
    except Exception as exc:
        raise HTTPException(
            status_code=500, detail=f"Failed to load site visit config: {exc}"
        ) from exc


@router.post("/site-visit")
async def set_site_visit_config(config: SiteVisitConfig):
    """
    Set the site visit configuration.

    Update site visit scheduling settings. Only provided fields are updated.

    EXAMPLES:
    - Block holidays: {"blocked_dates": ["2026-01-01", "2026-12-25"]}
    - Change available hours: {"default_slots": [9, 11, 14, 16]}
    - Allow weekends: {"weekdays_only": false}
    """
    try:
        db = wf_load_db()
        if "config" not in db:
            db["config"] = {}

        current = db["config"].get("site_visit", {})

        if config.blocked_dates is not None:
            current["blocked_dates"] = config.blocked_dates
        if config.default_slots is not None:
            current["default_slots"] = config.default_slots
        if config.weekdays_only is not None:
            current["weekdays_only"] = config.weekdays_only
        if config.min_days_ahead is not None:
            current["min_days_ahead"] = config.min_days_ahead

        current["updated_at"] = _now_iso()
        db["config"]["site_visit"] = current
        wf_save_db(db)

        print(f"[Config] Site visit updated: slots={current.get('default_slots')} weekdays_only={current.get('weekdays_only')}")

        return {
            "status": "ok",
            "config": current,
            "message": "Site visit configuration updated.",
        }
    except Exception as exc:
        raise HTTPException(
            status_code=500, detail=f"Failed to save site visit config: {exc}"
        ) from exc


# ---------------------------------------------------------------------------
# Manager Configuration Endpoints
# ---------------------------------------------------------------------------

class ManagerConfig(BaseModel):
    """
    Manager configuration for escalation detection.

    - names: List of registered manager names. Used to detect when clients
             ask to speak with a specific manager by name.
    """
    names: Optional[List[str]] = None


@router.get("/managers")
async def get_manager_config():
    """
    Get the current manager configuration.

    Returns registered manager names for escalation detection.
    """
    try:
        from backend.workflows.io.config_store import get_all_manager_config

        config = get_all_manager_config()
        return {
            "names": config.get("names", []),
            "source": "database",
        }
    except Exception as exc:
        raise HTTPException(
            status_code=500, detail=f"Failed to load manager config: {exc}"
        ) from exc


@router.post("/managers")
async def set_manager_config(config: ManagerConfig):
    """
    Set the manager configuration.

    Register manager names for escalation detection:
    - When clients mention these names, the system can detect escalation requests

    EXAMPLE:
    {"names": ["John", "Sarah", "Michael"]}
    """
    try:
        db = wf_load_db()
        if "config" not in db:
            db["config"] = {}

        current = db["config"].get("managers", {})

        if config.names is not None:
            current["names"] = config.names

        current["updated_at"] = _now_iso()
        db["config"]["managers"] = current
        wf_save_db(db)

        print(f"[Config] Managers updated: names={current.get('names')}")

        return {
            "status": "ok",
            "config": current,
            "message": "Manager configuration updated.",
        }
    except Exception as exc:
        raise HTTPException(
            status_code=500, detail=f"Failed to save manager config: {exc}"
        ) from exc


# ---------------------------------------------------------------------------
# Product Configuration Endpoints
# ---------------------------------------------------------------------------

class ProductConfig(BaseModel):
    """
    Product configuration for offer generation.

    - autofill_min_score: Similarity threshold (0.0-1.0) for auto-including
                          products in offers based on client preferences.
                          Default 0.5 = 50% match required.
    """
    autofill_min_score: Optional[float] = None


@router.get("/products")
async def get_product_config():
    """
    Get the current product configuration.

    Returns settings for product autofill in offer generation.
    """
    try:
        from backend.workflows.io.config_store import get_all_product_config

        config = get_all_product_config()
        return {
            "autofill_min_score": config.get("autofill_min_score", 0.5),
            "source": "database",
        }
    except Exception as exc:
        raise HTTPException(
            status_code=500, detail=f"Failed to load product config: {exc}"
        ) from exc


@router.post("/products")
async def set_product_config(config: ProductConfig):
    """
    Set the product configuration.

    Adjust product autofill behavior:
    - autofill_min_score: 0.0 = include all products, 1.0 = exact matches only

    EXAMPLES:
    - More suggestions: {"autofill_min_score": 0.3}
    - Fewer suggestions: {"autofill_min_score": 0.7}
    """
    if config.autofill_min_score is not None:
        if not 0.0 <= config.autofill_min_score <= 1.0:
            raise HTTPException(
                status_code=400,
                detail="autofill_min_score must be between 0.0 and 1.0"
            )

    try:
        db = wf_load_db()
        if "config" not in db:
            db["config"] = {}

        current = db["config"].get("products", {})

        if config.autofill_min_score is not None:
            current["autofill_min_score"] = config.autofill_min_score

        current["updated_at"] = _now_iso()
        db["config"]["products"] = current
        wf_save_db(db)

        print(f"[Config] Products updated: autofill_min_score={current.get('autofill_min_score')}")

        return {
            "status": "ok",
            "config": current,
            "message": "Product configuration updated.",
        }
    except Exception as exc:
        raise HTTPException(
            status_code=500, detail=f"Failed to save product config: {exc}"
        ) from exc


# ---------------------------------------------------------------------------
# Menus (Catering) Configuration Endpoints
# ---------------------------------------------------------------------------

class MenuItemConfig(BaseModel):
    """
    Configuration for a single dinner menu option.
    """
    menu_name: str
    courses: int = 3
    vegetarian: bool = False
    wine_pairing: bool = False
    price: str = "CHF 0"
    description: str = ""
    available_months: List[str] = []
    season_label: str = ""
    notes: List[str] = []
    priority: int = 1


class MenusConfig(BaseModel):
    """
    Menus (catering) configuration for the venue.

    - dinner_options: List of available dinner menus with pricing,
                      dietary info, and seasonal availability.
    """
    dinner_options: Optional[List[MenuItemConfig]] = None


@router.get("/menus")
async def get_menus_config():
    """
    Get the current menus (catering) configuration.

    Returns dinner menu options that clients can select from.
    If no custom menus are configured, returns built-in defaults.
    """
    try:
        from backend.workflows.io.config_store import get_all_menus_config

        config = get_all_menus_config()
        return {
            "dinner_options": config.get("dinner_options", []),
            "source": "database",
        }
    except Exception as exc:
        raise HTTPException(
            status_code=500, detail=f"Failed to load menus config: {exc}"
        ) from exc


@router.post("/menus")
async def set_menus_config(config: MenusConfig):
    """
    Set the menus (catering) configuration.

    Configure dinner menu options for the venue. Each menu includes:
    - menu_name: Display name
    - courses: Number of courses
    - vegetarian: Whether it's vegetarian-friendly
    - wine_pairing: Whether wine pairing is included
    - price: Price string (e.g., "CHF 92")
    - description: Menu description
    - available_months: Seasonal availability
    - season_label: Human-readable availability text
    - notes: Additional notes (e.g., ["vegetarian"])
    - priority: Sort order (lower = higher priority)

    EXAMPLE:
    {
      "dinner_options": [
        {
          "menu_name": "Garden Trio",
          "courses": 3,
          "vegetarian": true,
          "wine_pairing": true,
          "price": "CHF 92",
          "description": "Seasonal vegetarian menu...",
          "available_months": ["december", "january", "february"],
          "season_label": "Available December–February",
          "notes": ["vegetarian"],
          "priority": 1
        }
      ]
    }

    Set to empty array to reset to built-in defaults:
    {"dinner_options": []}
    """
    try:
        db = wf_load_db()
        if "config" not in db:
            db["config"] = {}

        current = db["config"].get("menus", {})

        if config.dinner_options is not None:
            # Convert to dict format for JSON storage
            current["dinner_options"] = [
                item.model_dump() for item in config.dinner_options
            ]

        current["updated_at"] = _now_iso()
        db["config"]["menus"] = current
        wf_save_db(db)

        count = len(current.get("dinner_options", []))
        print(f"[Config] Menus updated: {count} dinner options")

        return {
            "status": "ok",
            "config": current,
            "message": f"Menus configuration updated. {count} dinner option(s) configured.",
        }
    except Exception as exc:
        raise HTTPException(
            status_code=500, detail=f"Failed to save menus config: {exc}"
        ) from exc


# ---------------------------------------------------------------------------
# Catalog Configuration Endpoints (Product-Room Availability Mapping)
# ---------------------------------------------------------------------------

class ProductRoomMapItem(BaseModel):
    """
    Configuration for a single product-to-room mapping.
    """
    name: str
    category: str = "equipment"
    rooms: List[str] = []


class CatalogConfig(BaseModel):
    """
    Catalog configuration for product-room availability mapping.

    - product_room_map: Maps products to the rooms they're available in.
    """
    product_room_map: Optional[List[ProductRoomMapItem]] = None


@router.get("/catalog")
async def get_catalog_config():
    """
    Get the current catalog configuration.

    Returns product-to-room availability mappings.
    If no custom mapping is configured, returns built-in defaults.
    """
    try:
        from backend.workflows.io.config_store import get_all_catalog_config

        config = get_all_catalog_config()
        return {
            "product_room_map": config.get("product_room_map", []),
            "source": "database",
        }
    except Exception as exc:
        raise HTTPException(
            status_code=500, detail=f"Failed to load catalog config: {exc}"
        ) from exc


@router.post("/catalog")
async def set_catalog_config(config: CatalogConfig):
    """
    Set the catalog configuration.

    Configure which products are available in which rooms:
    - name: Product display name
    - category: Product category (av, equipment, lighting, furniture, supplies)
    - rooms: List of room names where this product is available

    EXAMPLE:
    {
      "product_room_map": [
        {"name": "Projector & Screen", "category": "av", "rooms": ["Room A", "Room B"]},
        {"name": "Stage Lighting", "category": "lighting", "rooms": ["Room C"]}
      ]
    }

    Set to empty array to reset to built-in defaults:
    {"product_room_map": []}
    """
    try:
        db = wf_load_db()
        if "config" not in db:
            db["config"] = {}

        current = db["config"].get("catalog", {})

        if config.product_room_map is not None:
            current["product_room_map"] = [
                item.model_dump() for item in config.product_room_map
            ]

        current["updated_at"] = _now_iso()
        db["config"]["catalog"] = current
        wf_save_db(db)

        count = len(current.get("product_room_map", []))
        print(f"[Config] Catalog updated: {count} product-room mappings")

        return {
            "status": "ok",
            "config": current,
            "message": f"Catalog configuration updated. {count} product mapping(s) configured.",
        }
    except Exception as exc:
        raise HTTPException(
            status_code=500, detail=f"Failed to save catalog config: {exc}"
        ) from exc


# ---------------------------------------------------------------------------
# FAQ Configuration Endpoints
# ---------------------------------------------------------------------------

class FAQItem(BaseModel):
    """
    Configuration for a single FAQ item.
    """
    category: str
    question: str
    answer: str
    related_links: List[str] = []


class FAQConfig(BaseModel):
    """
    FAQ configuration for venue-specific Q&A.

    - items: List of FAQ entries with category, question, and answer.
    """
    items: Optional[List[FAQItem]] = None


@router.get("/faq")
async def get_faq_config():
    """
    Get the current FAQ configuration.

    Returns venue-specific FAQ items for the Q&A page.
    If no custom FAQ is configured, returns built-in defaults.
    """
    try:
        from backend.workflows.io.config_store import get_all_faq_config

        config = get_all_faq_config()
        return {
            "items": config.get("items", []),
            "source": "database",
        }
    except Exception as exc:
        raise HTTPException(
            status_code=500, detail=f"Failed to load FAQ config: {exc}"
        ) from exc


@router.post("/faq")
async def set_faq_config(config: FAQConfig):
    """
    Set the FAQ configuration.

    Configure venue-specific FAQ items:
    - category: FAQ category (Parking, Catering, Booking, Equipment, Access)
    - question: The FAQ question
    - answer: The answer text
    - related_links: Optional related URLs

    EXAMPLE:
    {
      "items": [
        {
          "category": "Parking",
          "question": "Where can guests park?",
          "answer": "Underground parking available..."
        }
      ]
    }

    Set to empty array to reset to built-in defaults:
    {"items": []}
    """
    try:
        db = wf_load_db()
        if "config" not in db:
            db["config"] = {}

        current = db["config"].get("faq", {})

        if config.items is not None:
            current["items"] = [
                item.model_dump() for item in config.items
            ]

        current["updated_at"] = _now_iso()
        db["config"]["faq"] = current
        wf_save_db(db)

        count = len(current.get("items", []))
        print(f"[Config] FAQ updated: {count} items")

        return {
            "status": "ok",
            "config": current,
            "message": f"FAQ configuration updated. {count} item(s) configured.",
        }
    except Exception as exc:
        raise HTTPException(
            status_code=500, detail=f"Failed to save FAQ config: {exc}"
        ) from exc
