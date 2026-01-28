"""
Production-safe FastAPI application entrypoint.

This module provides a clean FastAPI app instance with NO import-time side effects:
- No bytecode cache clearing
- No environment mutations
- No subprocess spawning

For development with auto-launch behaviors, use: scripts/dev/dev_main.py
For production deployment, import directly: from app import app
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import os
import logging

# Configure logging (this is acceptable at import time - just sets up handlers)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# Environment mode detection (read-only, no mutations)
def _is_dev_mode() -> bool:
    """Check if running in development mode. Does NOT mutate environment."""
    env_value = os.getenv("ENV", "prod").lower()
    return env_value in ("dev", "development", "local")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifecycle manager for startup/shutdown events.

    Production-safe: validates configuration but does not clear caches
    (cache clearing is a dev-only concern handled by dev_main.py).
    """
    is_dev = _is_dev_mode()

    # Validate hybrid mode configuration (Gemini + OpenAI)
    try:
        from llm.provider_config import validate_hybrid_mode
        is_production = not is_dev
        is_valid, msg, _settings = validate_hybrid_mode(
            raise_on_failure=is_production,
            is_production=is_production,
        )
        if is_valid:
            logger.info("[Backend] %s", msg)
        else:
            logger.error("[Backend] %s", msg)
            logger.error("[Backend] Running in degraded mode - fix configuration!")
    except RuntimeError as e:
        logger.critical("[Backend] STARTUP BLOCKED: %s", e)
        raise
    except Exception as e:
        logger.warning("[Backend] Could not validate hybrid mode: %s", e)

    # Auth configuration warning
    auth_enabled = os.getenv("AUTH_ENABLED", "0") == "1"
    if not is_dev and not auth_enabled:
        logger.warning("[SECURITY] AUTH_ENABLED=0 in production - API is unprotected!")
        logger.warning("[SECURITY] Set AUTH_ENABLED=1 and configure API_KEY for production")

    yield
    # Shutdown logic (if any) goes here


def create_app() -> FastAPI:
    """Create and configure the FastAPI application.

    This is a factory function that returns a fully configured app.
    Safe to call multiple times (e.g., for testing).
    """
    is_dev = _is_dev_mode()

    app = FastAPI(title="AI Event Manager", lifespan=lifespan)

    # Import routers (lazy import to avoid circular dependencies)
    from api.routes import (
        tasks_router,
        events_router,
        config_router,
        clients_router,
        debug_router,
        snapshots_router,
        test_data_router,
        workflow_router,
        messages_router,
        emails_router,
        activity_router,
    )
    from api.agent_router import router as agent_router

    # Include route modules
    app.include_router(tasks_router)
    app.include_router(events_router)
    app.include_router(config_router)
    app.include_router(clients_router)

    # Debug router only in dev mode (exposes internal traces and logs)
    if is_dev:
        app.include_router(debug_router)

    app.include_router(snapshots_router)
    app.include_router(test_data_router)
    app.include_router(workflow_router)
    app.include_router(messages_router)
    app.include_router(emails_router)
    app.include_router(activity_router)
    app.include_router(agent_router)

    # Import middleware (lazy import)
    from api.middleware import TenantContextMiddleware, AuthMiddleware, setup_rate_limiting
    from api.middleware.request_limits import RequestSizeLimitMiddleware

    # Request size limit middleware (DoS protection)
    app.add_middleware(RequestSizeLimitMiddleware)

    # Tenant context middleware
    app.add_middleware(TenantContextMiddleware)

    # Auth middleware
    app.add_middleware(AuthMiddleware)

    # CORS configuration
    _configure_cors(app)

    # Rate limiting
    setup_rate_limiting(app)

    # Add root endpoint
    _add_root_endpoint(app, is_dev)

    return app


def _configure_cors(app: FastAPI) -> None:
    """Configure CORS middleware based on environment."""
    raw_origins = os.getenv("ALLOWED_ORIGINS")

    if raw_origins:
        allowed_origins = [o.strip() for o in raw_origins.split(",") if o.strip()]
        # Remove "*" if present (causes crash with allow_credentials=True)
        if "*" in allowed_origins:
            allowed_origins = [o for o in allowed_origins if o != "*"]

        app.add_middleware(
            CORSMiddleware,
            allow_origins=allowed_origins,
            allow_origin_regex=r"^https://.*\.lovable\.app$|^https://.*\.lovableproject\.com$",
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )
    else:
        # Dev default: localhost + Lovable domains
        app.add_middleware(
            CORSMiddleware,
            allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1|0\.0\.0\.0)(:\d+)?$|^https://.*\.lovable\.app$|^https://.*\.lovableproject\.com$",
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )


def _add_root_endpoint(app: FastAPI, is_dev: bool) -> None:
    """Add root health check endpoint."""

    @app.get("/")
    async def root():
        """Root health check endpoint.

        In production (ENV=prod), returns minimal status only.
        In dev mode, includes conversation/event counts for debugging.
        """
        if is_dev:
            from legacy.session_store import active_conversations
            from workflow_email import DB_PATH as WF_DB_PATH
            from utils import json_io

            if WF_DB_PATH.exists():
                with open(WF_DB_PATH, 'r', encoding='utf-8') as f:
                    database = json_io.load(f)
            else:
                database = {"events": []}

            return {
                "status": "AI Event Manager Running",
                "active_conversations": len(active_conversations),
                "total_saved_events": len(database["events"])
            }
        return {"status": "ok"}


# Create the default app instance
# This is what gets imported by uvicorn (e.g., uvicorn app:app)
app = create_app()
